import logging

import requests as http_requests
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from app.cuentas.throttle import bloqueado, ip_de, limpiar, registrar_fallo

from ..models import Rol, Sistema, UsuarioSistema
from .serializers import RolSerializer, SistemaSerializer

logger = logging.getLogger(__name__)

# Niveles de acceso definidos por la API Central.
NIVEL_SOPORTE = 4
NIVEL_SUPERUSUARIO = 5

# Códigos con los que la API Central identifica el sistema de tickets.
CODIGOS_SISTEMA_TICKETS = ("001", "0001", "1", "IAHELP", "TICKETS", "TIKETS")
NOMBRES_SISTEMA_TICKETS = ("ticket", "tikets", "iahelp")


class LoginView(APIView):
    """API Login que valida credenciales contra la API Central y verifica
    permisos por sistema_url.

    Flujo:
    1. Proxy de credenciales al API Central (puerto 8000)
    2. Valida que el usuario tenga permiso para la URL de este sistema
    3. Sincroniza usuario, sistemas, roles y permisos localmente
    4. Retorna tokens y datos de permisos
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        ip = ip_de(request)
        if username and bloqueado(ip, username):
            return Response(
                {"error": "Demasiados intentos fallidos. Intenta más tarde."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Capturar la URL actual de este sistema
        current_app_url = request.build_absolute_uri("/")

        # 1. Proxy to external API
        try:
            external_api_url = f"{settings.AUTH_SERVER_URL.rstrip('/')}/api/permisos/login/"
            response = http_requests.post(
                external_api_url, json={"username": username, "password": password}, timeout=10
            )

            if response.status_code == 200:
                data = response.json()

                # Obtener datos del usuario y permisos
                user_data = data.get("user", {})
                permisos_data = data.get("permisos", [])
                is_api_superuser = user_data.get("is_superuser", False)

                # ── Validación de Permiso: buscar por URL, Código o Nombre ──
                permiso_para_este_sistema = None
                for p in permisos_data:
                    p_url = p.get("sistema_url", "").rstrip("/") + "/"
                    app_url = current_app_url.rstrip("/") + "/"
                    p_cod = str(p.get("sistema_codigo", "")).strip().upper()
                    p_cod_clean = p_cod.lstrip('0')
                    p_nom = str(p.get("sistema_nombre", "")).strip().lower()
                    
                    if (
                        p_url == app_url
                        or p_cod in CODIGOS_SISTEMA_TICKETS
                        or p_cod_clean == "1"
                        or "TICKET" in p_cod
                        or "TIKET" in p_cod
                        or any(k in p_nom for k in NOMBRES_SISTEMA_TICKETS)
                    ):
                        permiso_para_este_sistema = p
                        break

                # Validar acceso: debe tener permiso para esta URL o ser superusuario
                if not permiso_para_este_sistema and not is_api_superuser:
                    return Response(
                        {
                            "error": "Acceso denegado: No tienes permisos para este sistema.",
                            "detail": f"URL '{current_app_url}' no está registrada en tus permisos.",
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

                # 2. Create/Get Local Shadow User
                user, created = User.objects.get_or_create(username=username)

                # Sincronizar metadatos del usuario
                user.first_name = user_data.get("first_name", user.first_name)
                user.last_name = user_data.get("last_name", user.last_name)
                user.email = user_data.get("email", user.email)

                if created:
                    user.set_unusable_password()
                user.save()
               
                # Sincronizar permisos (Sistemas y Roles) según API v2
                # Si no hay permisos y el usuario es superusuario, asignar automáticamente
                if not permisos_data and (is_api_superuser or user.is_superuser):
                    permisos_data = []
                    try:
                        sistemas_qs = Sistema.objects.filter(activo=True)
                        if not sistemas_qs.exists():
                            sistemas_qs = Sistema.objects.all()
                    except Exception:
                        sistemas_qs = Sistema.objects.all()

                    highest_rol = Rol.objects.order_by("-nivel_acceso").first()

                    for sistema in sistemas_qs:
                        if highest_rol:
                            rol_nombre = highest_rol.nombre
                            nivel_acceso = highest_rol.nivel_acceso
                        else:
                            rol_nombre = "Administrador (Super)"
                            nivel_acceso = NIVEL_SUPERUSUARIO

                        permisos_data.append(
                            {
                                "sistema_codigo": sistema.codigo,
                                "sistema_nombre": sistema.nombre,
                                "sistema_url": sistema.url or "",
                                "rol_nombre": rol_nombre,
                                "nivel_acceso": nivel_acceso,
                            }
                        )

                # Validar que el usuario tenga permisos asignados
                if not permisos_data and not is_api_superuser:
                    return Response(
                        {"error": "Usuario no tiene permisos asignados en el sistema"},
                        status=status.HTTP_403_FORBIDDEN,
                    )

                sistemas_sincronizados = []
                for p in permisos_data:
                    # 1. Sincronizar Sistema (incluyendo sistema_url)
                    sistema, _ = Sistema.objects.get_or_create(
                        codigo=p["sistema_codigo"],
                        defaults={
                            "nombre": p["sistema_nombre"],
                            "url": p.get("sistema_url", ""),
                        },
                    )
                    # Actualizar URL del sistema si cambió
                    sistema_url = p.get("sistema_url", "")
                    if sistema_url and sistema.url != sistema_url:
                        sistema.url = sistema_url
                        sistema.save()

                    # 2. Sincronizar Rol
                    rol, _ = Rol.objects.get_or_create(
                        nombre=p["rol_nombre"],
                        defaults={"nivel_acceso": p["nivel_acceso"]},
                    )
                    if rol.nivel_acceso != p["nivel_acceso"]:
                        rol.nivel_acceso = p["nivel_acceso"]
                        rol.save()

                    # 3. Vincular Usuario con Sistema y Rol
                    UsuarioSistema.objects.update_or_create(
                        user=user, sistema=sistema, defaults={"rol": rol}
                    )
                    sistemas_sincronizados.append(sistema.id)

                # Limpiar permisos antiguos revocados por la API
                if permisos_data:
                    UsuarioSistema.objects.filter(user=user).exclude(sistema_id__in=sistemas_sincronizados).delete()

                # Actualizar flags locales
                try:
                    if permiso_para_este_sistema:
                        max_nivel = int(permiso_para_este_sistema.get("nivel_acceso", 0))
                    else:
                        max_nivel = 0
                except Exception:
                    max_nivel = 0

                user.is_staff = max_nivel >= NIVEL_SOPORTE
                # Endurecido: superuser solo si el central lo declara explícitamente
                # (no basta un nivel alto en un permiso). No rompe TI legítimo.
                user.is_superuser = bool(is_api_superuser and max_nivel >= NIVEL_SUPERUSUARIO)
                user.save()
                logger.info(
                    "LOGIN central %s nivel=%s super=%s",
                    username, max_nivel, user.is_superuser,
                )

                # 3. Create Local Session
                login(request, user)
                limpiar(ip, username)

                # 4. Return response with permiso_sistema_actual for this URL
                response_data = dict(data)
                if permiso_para_este_sistema:
                    response_data["permiso_sistema_actual"] = permiso_para_este_sistema
                else:
                    response_data["permiso_sistema_actual"] = {
                        "sistema_nombre": "Acceso Superusuario",
                        "sistema_codigo": "SUPERUSER",
                        "sistema_url": current_app_url,
                        "rol_nombre": "Superusuario",
                        "nivel_acceso": NIVEL_SUPERUSUARIO,
                        "activo": True,
                    }

                return Response(response_data)
            else:
                if username:
                    registrar_fallo(ip, username)
                return Response(
                    {"error": "Credenciales inválidas en API externa"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
        except Exception as e:
            logger.error("Proxy Error: %s", e)
            return Response(
                {"error": "Error de conexión con el servidor de autenticación"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class ValidarPermisoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        codigo_sistema = request.data.get("codigo_sistema")
        try:
            permiso = UsuarioSistema.objects.get(
                user=request.user, sistema__codigo=codigo_sistema
            )
            return Response(
                {
                    "tiene_acceso": True,
                    "sistema": SistemaSerializer(permiso.sistema).data,
                    "roles": [RolSerializer(permiso.rol).data],
                }
            )
        except UsuarioSistema.DoesNotExist:
            return Response({"tiene_acceso": False}, status=status.HTTP_200_OK)


class MisSistemasView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        permisos = UsuarioSistema.objects.filter(user=request.user)
        sistemas = [p.sistema for p in permisos]
        serializer = SistemaSerializer(sistemas, many=True)
        return Response(serializer.data)
