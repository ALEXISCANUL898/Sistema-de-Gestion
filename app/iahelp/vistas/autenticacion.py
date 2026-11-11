"""Login, logout y paneles de entrada del Helpdesk."""

import logging
import requests as http_requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import redirect, render

from app.cuentas.models import CuentaExtension
from app.cuentas.throttle import bloqueado as _login_bloqueado, ip_de as _login_ip, limpiar as _login_limpiar, mensaje_bloqueo as _login_mensaje_bloqueo, registrar_fallo as _login_registrar_fallo

from ..models import Ticket, TicketMessage
from ..servicios.correo import EmailService
from ..servicios.ia_tickets import TicketAIService

from .comunes import (
    ADMIN_USERNAME,
    _buscar_permiso_sistema,
    _con_ultimo_mensaje,
    _destino_login,
    _es_admin_real,
    _filas_tickets,
    _leidos,
    _nivel_acceso,
    _nivel_de_permiso,
)

logger = logging.getLogger(__name__)

def intranet_home(request):
    """Pantalla principal tipo Intranet que muestra los accesos a sistemas."""
    return render(request, "intranet/home.html")


def login_view(request, system=None):
    """Pantalla de login con seguridad reforzada y validación por código de sistema."""
    
    # 1. SEGURIDAD: si ya está autenticado y tiene permiso, no repetir el login
    if request.user.is_authenticated:
        if request.session.get(f"permiso_{system}"):
            nivel = _nivel_acceso(request, system)
            if system == "Almacen":
                destino = "almacen:bitacora" if nivel >= 6 else "cuentas:seleccionar_perfil"
                return redirect(destino)
            return redirect(_destino_login(system, nivel))

        # Sin permiso para este sistema: reautenticar limpiamente
        logout(request)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        if not username or not password:
            messages.error(request, "Usuario y contraseña son requeridos.")
            return render(request, "registration/login.html", {"system": system})

        _ip = _login_ip(request)
        if _login_bloqueado(_ip, username):
            messages.error(request, _login_mensaje_bloqueo())
            return render(request, "registration/login.html", {"system": system})

        try:
            external_api_url = f"{settings.AUTH_SERVER_URL.rstrip('/')}/api/permisos/login/"
            response = http_requests.post(
                external_api_url, json={"username": username, "password": password}, timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                user_data = data.get("user", {})
                permisos_data = data.get("permisos", [])
                
                logger.info(
                    "LOGIN: %s autenticado en el API central; buscando permiso para '%s'",
                    username,
                    system,
                )

                # Permiso del sistema actual: por código, nombre o URL
                current_url_norm = request.build_absolute_uri("/").strip().lower().rstrip("/")
                permiso_actual = _buscar_permiso_sistema(permisos_data, system, current_url_norm)

                if permiso_actual:
                    logger.info(
                        "LOGIN: permiso encontrado %s (código %s, nivel %s)",
                        permiso_actual.get("sistema_nombre"),
                        permiso_actual.get("sistema_codigo"),
                        permiso_actual.get("nivel_acceso"),
                    )
                else:
                    logger.warning(
                        "LOGIN: sin coincidencia para %s; se usan flags de superusuario",
                        system,
                    )

                is_local_admin = username == ADMIN_USERNAME
                is_api_admin = user_data.get("is_superuser", False)
                nivel_actual = _nivel_de_permiso(permiso_actual)

                # Validación crítica: permiso activo, admin local o superusuario central
                if nivel_actual <= 0 and not (is_local_admin or is_api_admin):
                    logger.warning(
                        "ACCESO DENEGADO: %s no tiene permisos para el sistema %s",
                        username,
                        system,
                    )
                    messages.error(
                        request, f"No tiene permisos para acceder al sistema {system.upper()}."
                    )
                    return render(request, "registration/login.html", {"system": system})

                # Sincronización de Usuario y Permisos Locales
                user, created = User.objects.get_or_create(username=username)
                user.first_name = user_data.get("first_name", user.first_name)
                user.last_name = user_data.get("last_name", user.last_name)
                user.email = user_data.get("email", user.email)

                # El estatus de superusuario local solo se otorga si es admin local
                # o superusuario en la API Central
                user.is_superuser = is_local_admin or is_api_admin
                user.is_staff = user.is_superuser or nivel_actual >= 4
                user.save()

                # LOGIN
                login(request, user)
                _login_limpiar(_ip, username)

                # Sincronizar extensión local de nivel (la crean TI o este login)
                try:
                    if nivel_actual in (1, 3, 4, 6):
                        CuentaExtension.objects.update_or_create(
                            usuario=user, defaults={"nivel": nivel_actual}
                        )
                except Exception as exc:
                    logger.warning(f"No se pudo sincronizar CuentaExtension: {exc}")
                
                # Persistencia de permisos en sesión
                request.session["access_token"] = data.get("access", "")
                request.session["refresh_token"] = data.get("refresh", "")
                request.session["permisos_full"] = permisos_data
                session_key = f"permiso_{system}"

                # Asignación estricta: solo el permiso del sistema actual
                if permiso_actual:
                    request.session[session_key] = permiso_actual
                else:
                    # Admin global sin permiso específico: nivel 5
                    request.session[session_key] = {
                        "nivel_acceso": 5 if user.is_superuser else 0,
                        "sistema_nombre": system,
                    }

                # Limpiar permisos de otros sistemas para evitar colisiones
                for otro in (
                    "iahelp", "enkontrol", "reservaciones", "intranet",
                    "PRESTAMOS", "Almacen", "Catalogos", "Auditoria",
                ):
                    if otro != system:
                        request.session.pop(f"permiso_{otro}", None)

                request.session.pop("last_permiso_check", None)

                nivel_final = _nivel_acceso(request, system)
                logger.info("LOGIN EXITOSO: %s en %s (Nivel %s)", username, system, nivel_final)
                messages.success(request, f"Bienvenido, {user.first_name or user.username}!")
                return redirect(_destino_login(system, nivel_final))

            if response.status_code in (401, 403):
                restantes = _login_registrar_fallo(_ip, username)
                if restantes == 0:
                    messages.error(request, _login_mensaje_bloqueo())
                elif response.status_code == 401:
                    messages.error(
                        request, "Credenciales inválidas: revisa el usuario y la contraseña."
                    )
                else:
                    try:
                        detalle = response.json().get("error", "")
                    except Exception:
                        detalle = ""
                    messages.error(
                        request, f"Acceso denegado por el servidor central. {detalle}".strip()
                    )
            else:
                messages.error(
                    request,
                    f"El servidor central devolvió estado {response.status_code}. Intenta de nuevo.",
                )

        except Exception as e:
            logger.error(f"Error de conexión en login: {e}")
            messages.error(request, "Error crítico de conexión con el servidor de autenticación.")

    return render(request, "registration/login.html", {"system": system})


def logout_view(request):
    """Cerrar sesión y redirigir al login."""
    logout(request)
    return redirect("intranet_home")


@login_required
def index(request):
    """Crear un nuevo ticket y analizarlo con IA. La IA determina automáticamente el nivel."""
    
    # 1. VERIFICACIÓN DE SEGURIDAD EN TIEMPO REAL
    nivel_acceso = _nivel_acceso(request, "iahelp")
    is_real_admin = _es_admin_real(request.user)

    # Sin permiso activo (y sin ser admin local) no se puede crear tickets
    if not is_real_admin and nivel_acceso <= 0:
        logout(request)
        messages.error(request, "Acceso denegado. No tiene permisos activos para este sistema.")
        return redirect("login")

    # El personal de soporte (nivel 4+) trabaja en el panel, no en el formulario
    if is_real_admin or nivel_acceso >= 4:
        return redirect("support_dashboard")

    nivel_usuario = nivel_acceso
    ticket = None

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()

        if not title or not description:
            messages.error(request, "El título y la descripción son obligatorios.")
            context = {
                "ticket": ticket,
                "email_user": getattr(request.user, "email", ""),
                "email_analista_erp": getattr(settings, "EMAIL_ERP_ANALISTA", ""),
            }
            return render(request, "soporte/index.html", context)

        # Usar el nivel de acceso del sistema actual
        user_email = request.POST.get("email", "").strip() or request.POST.get("correo", "").strip()
        if not user_email:
            user_email = request.user.email or None

        # Si se proporcionó un email y difiere del que tiene el usuario, actualizarlo
        if user_email and request.user.email != user_email:
            User.objects.filter(id=request.user.id).update(email=user_email)
            request.user.email = user_email

        
        ticket = Ticket.objects.create(
            user=request.user,
            title=title,
            description=description,
            usuario=(
                request.user.first_name if request.user.first_name else request.user.username
            ),
            email=user_email,
            nivel=1,  # Valor temporal, será actualizado por la IA
            nivel_usuario=nivel_usuario,  # Guardar nivel del usuario
        )

        # Análisis IA: en fondo si el worker vive, sincrónico si no (etapa 4C).
        from app.iahelp.servicios.fondo import (
            cola_viva, encolar_analisis_ticket, aplicar_analisis_ticket,
        )
        if cola_viva():
            encolar_analisis_ticket(ticket.id, nivel_usuario)
            messages.success(
                request,
                "Ticket recibido. La IA lo está clasificando; aparecerá aquí en breve.",
            )
        else:
            # Analizar con IA
            try:
                # Verificar el nivel máximo del usuario
                is_specialist = nivel_usuario >= 3

                svc = TicketAIService()
                analysis = svc.analyze(
                    description, ticket=ticket, is_high_priority=is_specialist
                )
                ai_nivel = aplicar_analisis_ticket(ticket, analysis, nivel_usuario)

                # Enviar correos: escenario 1 (usuario) + escenario 2 (soporte)
                try:
                    EmailService.send_ticket_created_to_user(ticket)
                    EmailService.send_new_ticket_to_support(ticket)
                except Exception as e:
                    logger.warning(f"No se pudo enviar notificación por correo: {e}")

                messages.success(
                    request, f"Ticket creado y clasificado como Nivel {ai_nivel}."
                )

            except Exception as e:
                logger.error("Error al analizar ticket con IA: %s", str(e))
                messages.warning(
                    request,
                    "Ticket creado, pero el análisis de IA falló. "
                    "Se puede reintentar más tarde.",
                )

    context = {
        "ticket": ticket,
        "email_user": getattr(request.user, "email", ""),
        "email_analista_erp": getattr(settings, "EMAIL_ERP_ANALISTA", ""),
    }
    return render(request, "soporte/index.html", context)


@login_required
def dashboard(request):
    """Panel de tickets del usuario — muestra solo sus propios tickets (con unread)."""
    
    # 1. Verificar permiso específico en la sesión
    nivel_acceso = _nivel_acceso(request, "iahelp")
    is_real_admin = _es_admin_real(request.user)
    if not is_real_admin and nivel_acceso <= 0:
        return redirect("login")

    # El personal de soporte (nivel 4+) trabaja en el panel de soporte
    if is_real_admin or nivel_acceso >= 4:
        return redirect("support_dashboard")

    # Tickets activos del usuario (último mensaje precargado: 2 queries, no N+1)
    tickets_qs = _con_ultimo_mensaje(
        Ticket.objects.filter(
            Q(user=request.user) & (Q(status="Abierto") | Q(status="En Progreso"))
        ).order_by("-created_at"),
        TicketMessage,
    )

    tickets = _filas_tickets(tickets_qs, _leidos(request))

    abiertos_count = sum(1 for tk in tickets if tk["status"] == "Abierto")
    en_progreso_count = sum(1 for tk in tickets if tk["status"] == "En Progreso")
    critica_count = sum(1 for tk in tickets if tk["priority"] == "Crítica")
    urgente_count = sum(1 for tk in tickets if tk["priority"] == "Urgente")

    context = {
        "tickets": tickets,
        "abiertos_count": abiertos_count,
        "en_progreso_count": en_progreso_count,
        "critica_count": critica_count,
        "urgente_count": urgente_count,
    }
    return render(request, "soporte/dashboard.html", context)
