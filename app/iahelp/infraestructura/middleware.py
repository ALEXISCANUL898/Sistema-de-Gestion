"""Middleware de permisos por sistema en tiempo real.

Comprueba que el permiso guardado en la sesión siga vigente en la API Central
(con caché) y expulsa al usuario cuando el acceso fue revocado.
"""

import logging
import time
from urllib.parse import urlparse

import requests as http_requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.messages import get_messages
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"

# Niveles de acceso definidos por la API Central.
NIVEL_SOPORTE = 4
NIVEL_TI_GLOBAL = 6

# Frecuencia de revalidación del permiso contra la API Central.
CACHE_PERMISO_SEGUNDOS = 300
TIMEOUT_API_SEGUNDOS = 2

# Permisos de sistema que el login deja en la sesión.
CLAVES_PERMISO_SESION = (
    "permiso_iahelp",
    "permiso_enkontrol",
    "permiso_reservas",
    "permiso_reservaciones",
    "permiso_intranet",
    "permiso_PRESTAMOS",
    "permiso_Almacen",
    "permiso_Catalogos",
    "permiso_Auditoria",
    "permiso_cuentas",
)

# Rutas que nunca pasan por la validación de permisos.
RUTAS_LIBRES = (
    "/static/",
    "/media/",
    "/admin/",
    "/cuentas/perfil/",
    "/cuentas/api/",
)
RUTAS_LIBRES_EXACTAS = ("/", "/manifest.json", "/favicon.ico")

# Prefijo de URL -> (clave del permiso en sesión, código del sistema en la API).
SISTEMAS_POR_RUTA = (
    ("/econtrol/", "permiso_enkontrol", "ENKONTROL"),
    ("/reservaciones/", "permiso_reservas", "RESERVACIONES"),
    ("/prestamos/", "permiso_PRESTAMOS", "PRESTAMOS"),
    ("/intranet/", "permiso_intranet", "INTRANET"),
    ("/almacen/", "permiso_Almacen", "ALMACEN"),
    ("/catalogos/", "permiso_Catalogos", "CATALOGOS"),
    ("/cuentas/ti/", "permiso_cuentas", "CUENTAS"),
)
SISTEMA_POR_DEFECTO = ("permiso_iahelp", "IAHELP")

# Rutas que exigen al menos NIVEL_SOPORTE.
RUTAS_SOPORTE = ("/soporte/", "/reportes/", "/chat-ia/")

# Destino cuando el usuario perdió el permiso del sistema.
LOGIN_POR_SISTEMA = {
    "ENKONTROL": "econtrol_login",
    "RESERVACIONES": "reservas_login",
    "PRESTAMOS": "prestamos_login",
    "INTRANET": "intranet_login",
    "ALMACEN": "almacen_login",
    "CATALOGOS": "catalogos_login",
    "CUENTAS": "almacen_login",
    "IAHELP": "login",
}


# ── Comparadores de permisos ────────────────────────────────────────────────
# La API Central no siempre usa el mismo código para un sistema, así que cada
# comparador acepta las variantes históricas (código, código sin ceros y nombre).


def _coincide_iahelp(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("001", "0001", "1", "IAHELP", "TICKETS", "TIKETS")
        or codigo_limpio == "1"
        or "IAHELP" in codigo
        or "TICKET" in codigo
        or "TIKET" in codigo
        or any(k in nombre for k in ("ticket", "tikets", "iahelp", "ia_help"))
    )


def _coincide_enkontrol(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("002", "0002", "2", "ENKONTROL", "EK")
        or codigo_limpio == "2"
        or "ENKONTROL" in codigo
        or "enkontrol" in nombre
    )


def _coincide_reservaciones(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("003", "0003", "3", "RESERVACIONES", "RESERVAS")
        or codigo_limpio == "3"
        or "RESERV" in codigo
        or any(k in nombre for k in ("reserva", "reservacion"))
    )


def _coincide_intranet(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("004", "0004", "005", "0005", "4", "5", "INTRANET")
        or codigo_limpio in ("4", "5")
        or "INTRANET" in codigo
        or "intranet" in nombre
    )


def _coincide_prestamos(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("005", "0005", "006", "0006", "5", "6", "PRESTAMOS", "PRESTAMO")
        or codigo_limpio in ("5", "6")
        or "PRESTAMO" in codigo
        or "prestamo" in nombre
    )


def _coincide_almacen(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("004", "0004", "4", "ALMACEN")
        or "almacen" in nombre
        or "almacén" in nombre
    )


def _coincide_catalogos(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("004", "0004", "4", "ALMACEN", "005", "0005", "5", "CATALOGOS", "CATALOGO")
        or "catalogo" in nombre
        or "catálogo" in nombre
        or "almacen" in nombre
        or "almacén" in nombre
    )


def _coincide_cuentas(codigo, codigo_limpio, nombre, permiso):
    return (
        codigo in ("004", "005", "4", "5", "ALMACEN", "CATALOGOS")
        or "almacen" in nombre
        or "catalogo" in nombre
    ) and int(permiso.get("nivel_acceso", 0)) >= NIVEL_SOPORTE


COINCIDENCIAS = {
    "IAHELP": _coincide_iahelp,
    "ENKONTROL": _coincide_enkontrol,
    "RESERVACIONES": _coincide_reservaciones,
    "INTRANET": _coincide_intranet,
    "PRESTAMOS": _coincide_prestamos,
    "ALMACEN": _coincide_almacen,
    "CATALOGOS": _coincide_catalogos,
    "CUENTAS": _coincide_cuentas,
}


def _descartar_mensajes(request):
    """Vacía los mensajes pendientes (p. ej. el 'Bienvenido' del login)."""
    for _ in get_messages(request):
        pass


def _sistema_de_la_ruta(path):
    """Devuelve (clave de sesión, código de sistema) según el prefijo de la URL."""
    for prefijo, clave, codigo in SISTEMAS_POR_RUTA:
        if path.startswith(prefijo):
            return clave, codigo
    return SISTEMA_POR_DEFECTO


def _es_ti_global(request):
    """True si el usuario es Administrador TI por cualquier vía:
    superusuario, extensión local nivel 6, o algún permiso en sesión con nivel >= 6."""
    try:
        user = request.user
        if user.is_superuser or user.username == ADMIN_USERNAME:
            return True
        try:
            if int(user.extension.nivel) >= NIVEL_TI_GLOBAL:
                return True
        except Exception:
            pass
        for clave in CLAVES_PERMISO_SESION:
            try:
                if int((request.session.get(clave) or {}).get("nivel_acceso", 0)) >= NIVEL_TI_GLOBAL:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


class SecurePermissionMiddleware:
    """
    Middleware para garantizar que el usuario tenga los permisos correctos
    para el sistema que está intentando acceder en tiempo real.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if (
            "/login/" in path
            or "/logout/" in path
            or path in RUTAS_LIBRES_EXACTAS
            or path.startswith(RUTAS_LIBRES)
        ):
            return self.get_response(request)

        # TI (Nivel 6) es global: su panel cruza /catalogos/, /almacen/ y /cuentas/.
        # El login guarda un solo permiso de sistema en sesión, así que a TI se le
        # da paso sin exigir el permiso específico de cada namespace.
        if request.user.is_authenticated and _es_ti_global(request):
            return self.get_response(request)

        if request.user.is_authenticated:
            system_key, target_codigo = _sistema_de_la_ruta(path)

            token = request.session.get("access_token")

            # Solo verificamos en peticiones de navegación (HTML)
            is_main_request = request.headers.get("x-requested-with") != "XMLHttpRequest"

            # Caché de 5 minutos: evita que cada navegación bloquee 5s contra la API central.
            # Con runserver (1 proceso) ese bloqueo congela las demás pestañas/PCs.
            now = time.time()
            last_check = request.session.get("last_permiso_check", 0)
            needs_check = (now - last_check) > CACHE_PERMISO_SEGUNDOS

            # Si el AUTH_SERVER apunta a este mismo servidor, no auto-llamarse:
            # causa interbloqueo con runserver y espera innecesaria.
            try:
                _auth_host = urlparse(settings.AUTH_SERVER_URL).netloc.split(":")[0]
                _req_host = request.get_host().split(":")[0]
                _es_mismo = _auth_host in (_req_host, "127.0.0.1", "localhost") or _req_host in (
                    _auth_host,
                    "127.0.0.1",
                    "localhost",
                )
            except Exception:
                _es_mismo = False

            if is_main_request and token and needs_check and not _es_mismo:
                try:
                    request.session["last_permiso_check"] = now
                    # Intentar sincronizar con la API Central
                    # Probamos el endpoint de 'me' o el de 'usuario'
                    verify_url = f"{settings.AUTH_SERVER_URL.rstrip('/')}/api/permisos/me/"
                    logger.info(
                        f"Verificando permisos en tiempo real para {request.user.username} en {verify_url}"
                    )

                    api_response = http_requests.get(
                        verify_url,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=TIMEOUT_API_SEGUNDOS,
                    )

                    logger.info(f"Respuesta API Central: {api_response.status_code}")

                    if api_response.status_code == 200:
                        fresh_data = api_response.json()
                        fresh_permisos = fresh_data.get("permisos", [])
                        logger.info(
                            f"MIDDLEWARE: fresh_permisos para {request.user.username}: {fresh_permisos}"
                        )

                        # Buscar el permiso de este sistema en la respuesta fresca.
                        coincide = COINCIDENCIAS.get(target_codigo)
                        permiso_actual = None
                        for p in fresh_permisos:
                            p_cod = str(p.get("sistema_codigo", "")).strip().upper()
                            p_cod_clean = p_cod.lstrip("0")
                            p_nom = str(p.get("sistema_nombre", "")).strip().lower()
                            if coincide and coincide(p_cod, p_cod_clean, p_nom, p):
                                permiso_actual = p
                                break

                        # VALIDACIÓN CRÍTICA: Si el usuario existe pero ya no tiene este permiso
                        is_local_admin = request.user.username == ADMIN_USERNAME
                        if not permiso_actual and not is_local_admin:
                            logger.error(
                                f"SEGURIDAD: Permiso revocados en API para {request.user.username} "
                                f"(Sistema: {target_codigo})"
                            )

                            # Limpiar mensajes previos (como el de 'Bienvenido') para evitar confusión
                            _descartar_mensajes(request)

                            auth_logout(request)
                            rotate_token(request)
                            messages.error(
                                request,
                                f"Acceso denegado: No tiene permisos activos para el sistema {target_codigo}.",
                            )

                            return redirect(LOGIN_POR_SISTEMA.get(target_codigo, "intranet_home"))

                        # Actualizar nivel y staff status
                        if permiso_actual:
                            logger.info(
                                f"MIDDLEWARE: Permiso validado para {request.user.username} en "
                                f"{target_codigo} (Nivel {permiso_actual.get('nivel_acceso')})"
                            )
                            request.session[system_key] = permiso_actual
                            nivel = int(permiso_actual.get("nivel_acceso", 0))
                            request.user.is_staff = nivel >= NIVEL_SOPORTE
                            request.user.save()

                    elif api_response.status_code == 404:
                        # Si el endpoint /me/ no existe, no expulsamos,
                        # simplemente registramos y seguimos con la sesión local.
                        logger.info(
                            "API Central no soporta verificación en tiempo real (/me/). Usando sesión local."
                        )

                    elif api_response.status_code in (401, 403):
                        logger.error(
                            f"SEGURIDAD: Token inválido o usuario bloqueado (Status {api_response.status_code})"
                        )
                        # Remove only authentication-related data, keep CSRF token
                        keys_to_clear = [
                            k
                            for k in request.session.keys()
                            if k.startswith("permiso_") or k == "access_token"
                        ]
                        for k in keys_to_clear:
                            del request.session[k]
                        # Do NOT flush or cycle the session to preserve CSRF token
                        auth_logout(request)
                        rotate_token(request)
                        return redirect("login")

                except Exception as e:
                    logger.warning(
                        f"Error de conexión con API Central: {e}. "
                        "Se mantiene sesión local temporalmente."
                    )

            # Validación de Nivel de Soporte
            permiso = request.session.get(system_key)

            if request.user.username != ADMIN_USERNAME:
                if not permiso:
                    if path != "/intranet/":
                        messages.error(
                            request,
                            "Acceso denegado: tu cuenta no tiene permiso activo para este módulo.",
                        )
                        return redirect("intranet_home")
                else:
                    nivel_acceso = int(permiso.get("nivel_acceso", 0))
                    if any(ruta in path for ruta in RUTAS_SOPORTE) and nivel_acceso < NIVEL_SOPORTE:
                        logger.error(
                            f"ACCESO RESTRINGIDO: {request.user.username} nivel {nivel_acceso} "
                            f"intentó entrar a {path}. EXPULSANDO."
                        )

                        # Limpiar mensajes previos para evitar confusión
                        _descartar_mensajes(request)

                        auth_logout(request)
                        messages.error(request, "Nivel de acceso insuficiente para esta sección.")
                        return redirect("login")

        response = self.get_response(request)
        return response
