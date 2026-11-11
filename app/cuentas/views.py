import logging
import mimetypes
import os.path
from pathlib import Path

import requests as http_requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from app.auditoria.models import Bitacora

from .decorators import nivel_requerido
from .forms import (
    CuentaCreateForm,
    CuentaEditForm,
    LoginForm,
    PerfilForm,
    PerfilPINForm,
)
from .models import CuentaExtension, Perfil

logger = logging.getLogger(__name__)
MAX_INTENTOS = getattr(settings, "PIN_MAX_INTENTOS", 5)
BLOQUEO_MINUTOS = getattr(settings, "PIN_BLOQUEO_MINUTOS", 15)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _registrar_bitacora(perfil, accion, detalle="", request=None):
    ip = request.META.get("REMOTE_ADDR", "") if request else ""
    Bitacora.objects.create(perfil=perfil, accion=accion, detalle=detalle, ip=ip)


# ─── Login de cuenta ──────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect("cuentas:seleccionar_perfil")
    from .throttle import bloqueado, registrar_fallo, limpiar, mensaje_bloqueo, ip_de
    _ip = ip_de(request)
    form = LoginForm(request.POST or None)
    if request.method == "POST":
        _u = (request.POST.get("username") or "").strip()
        if _u and bloqueado(_ip, _u):
            form.add_error(None, mensaje_bloqueo())
        elif form.is_valid():
            limpiar(_ip, form.user.username)
            login(request, form.user)
            return redirect("cuentas:seleccionar_perfil")
        elif _u and request.POST.get("password"):
            _rest = registrar_fallo(_ip, _u)
            if _rest == 0:
                form.add_error(None, mensaje_bloqueo())
    return render(request, "cuentas/login.html", {"form": form})


def logout_view(request):
    perfil = getattr(request, "perfil_activo", None)
    if perfil:
        _registrar_bitacora(perfil, "LOGOUT", request=request)
    logout(request)
    return redirect("intranet_home")


# ─── Selección de perfil (local-primero + API Central opcional) ───────────────

@login_required(login_url="cuentas:login")
def seleccionar_perfil(request):
    """
    Fuente de verdad: perfiles LOCALES (los crea TI y son los únicos que
    entiende PerfilActivoMiddleware). La API Central se intenta solo como
    complemento cuando hay access_token; si falla, se usan los locales.
    """
    # 1. Locales siempre (IDs compatibles con el middleware de sesión)
    perfiles_locales = list(
        Perfil.objects.filter(usuario=request.user, activo=True)
        .values("id", "nombre", "puesto", "firma", "rol_almacen", "central_id")
    )
    for p in perfiles_locales:
        # Avatar: construir URL desde el campo firma local
        p["firma_url"] = (settings.MEDIA_URL + p["firma"]) if p.get("firma") else ""

    perfiles = list(perfiles_locales)
    error_api = None
    access_token = request.session.get("access_token", "")

    if access_token:
        try:
            from django.conf import settings as dj_settings
            api_base = dj_settings.AUTH_SERVER_URL.rstrip("/")
            permiso_almacen = request.session.get("permiso_Almacen", {})
            sistema_codigo = permiso_almacen.get("sistema_codigo", "004")
            resp = http_requests.get(
                f"{api_base}/api/permisos/mis-identidades/",
                params={"sistema": sistema_codigo},  # ej. "004" o "ALM"
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5,
            )
            if resp.status_code == 200:
                raw = resp.json()
                if not isinstance(raw, list):
                    raw = []
                # Normalizar campos de la API al formato que usa la plantilla
                for p in raw:
                    firma_rel = p.get("firma", "") or ""
                    if firma_rel and not firma_rel.startswith("http"):
                        p["firma_url"] = f"{api_base}{firma_rel}"
                    else:
                        p["firma_url"] = firma_rel
                    # Alias de nombre
                    p["nombre"] = p.get("nombre_completo", p.get("nombre", ""))
                    # Alias de rol (la API devuelve rol_nombre, la app usa rol_almacen)
                    p["rol_almacen"] = p.get("rol_almacen") or p.get("rol_nombre", "")
                # Unión: los centrales ya espejados se omiten (ya salen como locales);
                # los no espejados se agregan (ingresar_pin los valida vía central
                # y crea su espejo al primer login).
                espejados_id = {x.get("central_id") for x in perfiles_locales if x.get("central_id")}
                espejados_nom = {(x.get("nombre") or "").strip().lower() for x in perfiles_locales}
                for p in raw:
                    try:
                        cid = int(p.get("id"))
                    except (TypeError, ValueError):
                        continue
                    if cid in espejados_id or (p.get("nombre") or "").strip().lower() in espejados_nom:
                        continue
                    perfiles.append(p)
                logger.info(f"PERFILES: {len(perfiles_locales)} locales + {len(raw)} centrales para {request.user.username}")
            else:
                logger.warning(f"PERFILES API: estado {resp.status_code} para {request.user.username}")
                if not perfiles:
                    error_api = f"La API devolvió estado {resp.status_code} y no hay perfiles locales."
        except Exception as exc:
            logger.error(f"PERFILES API ERROR: {exc}")
            if not perfiles:
                error_api = "No se pudo conectar con la API de identidades y no hay perfiles locales."

    # Guardar en sesión para la ruta heredada central de ingresar_pin
    request.session["perfiles_disponibles"] = perfiles

    return render(request, "cuentas/seleccionar_perfil.html", {
        "perfiles": perfiles,
        "error_api": error_api,
    })


def _nivel_cuenta(user, request):
    """Nivel de la cuenta: primero CuentaExtension local, luego sesión central."""
    try:
        return int(user.extension.nivel)
    except Exception:
        pass
    try:
        return int(request.session.get("permiso_Almacen", {}).get("nivel_acceso", 0))
    except Exception:
        return 0


def _destino_por_nivel(nivel):
    if nivel == 1:
        return "almacen:mis_vales"
    elif nivel == 3:
        return "almacen:bandeja"
    elif nivel == 4:
        return "almacen:dashboard_gerencia"
    elif nivel >= 6:
        return "cuentas:ti_dashboard"
    return "intranet_home"


def _bytes_son_imagen(data):
    """True si los bytes son una imagen real (no una página de error)."""
    if not data or len(data) < 16 or len(data) > 2 * 1024 * 1024:
        return False
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"\xff\xd8" or \
       data[:6] in (b"GIF87a", b"GIF89a") or data[:4] == b"RIFF":
        return True
    try:
        from PIL import Image
        from io import BytesIO
        im = Image.open(BytesIO(data))
        im.verify()
        return True
    except Exception:
        return False


def sincronizar_firma_espejo(perfil, firma_url, api_base="", access_token=""):
    """Descarga la firma del central si es nueva o cambió. Devuelve True si actualizó.
    Las firmas ya estampadas en vales (snapshots) nunca se tocan: son historia."""
    if not firma_url:
        return False
    normalizada = (firma_url.split("?")[0] or "")[:255]
    if perfil.firma and (perfil.firma_central or "") == normalizada:
        return False  # ya está sincronizada
    try:
        url = firma_url if firma_url.startswith("http") else (api_base.rstrip("/") + firma_url)
        r = http_requests.get(
            url, headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
        )
        ct = r.headers.get("Content-Type", "")
        cuerpo = r.content or b""
        if r.status_code == 200 and ct.startswith("image") and _bytes_son_imagen(cuerpo):
            base = os.path.basename(normalizada) or f"firma_{perfil.pk}.png"
            if perfil.firma:
                perfil.firma.delete(save=False)
            perfil.firma.save(base, ContentFile(cuerpo), save=False)
            perfil.firma_central = normalizada
            perfil.save(update_fields=["firma", "firma_central"])
            return True
    except Exception as exc:
        logger.warning(f"FIRMA ESPEJO ERROR: {exc}")
    return False


def _espejar_identidad_central(request, identidad_id, perfil_data, firma_url="", api_base="", access_token=""):
    """Crea/actualiza el Perfil local espejo de una identidad central validada.
    Devuelve el Perfil local o None si no se pudo crear (nunca rompe el login)."""
    try:
        nombre = (perfil_data.get("nombre") or "").strip()[:255]
        if not nombre:
            return None
        espejo = Perfil.objects.filter(usuario=request.user, central_id=int(identidad_id)).first()
        if espejo is None:
            espejo = Perfil.objects.filter(usuario=request.user, central_id__isnull=True, nombre=nombre).first()
        if espejo is None:
            espejo = Perfil(usuario=request.user, nombre=nombre, central_id=int(identidad_id))
        espejo.nombre = nombre
        espejo.puesto = (perfil_data.get("puesto") or espejo.puesto or "")[:255]
        rol = (perfil_data.get("rol_almacen") or "").strip().upper()
        espejo.rol_almacen = rol if rol in ("ENCARGADO", "DESPACHADOR") else espejo.rol_almacen
        espejo.central_id = int(identidad_id)
        espejo.activo = True
        if not espejo.pin_hash:
            espejo.pin_hash = "!"  # sin PIN local: solo se valida vía central
        espejo.save()
        # Sincronizar firma: descarga si es nueva o cambió en el central
        sincronizar_firma_espejo(espejo, firma_url, api_base, access_token)
        return espejo
    except Exception as exc:
        logger.error(f"ESPEJO IDENTIDAD ERROR: {exc}")
        return None


def _ingresar_pin_local(request, perfil):
    """Valida el PIN contra la BD local (los PINs de TI solo existen aquí)."""
    if not perfil.activo:
        messages.error(request, "Perfil desactivado. Contacta al administrador.")
        return redirect("cuentas:seleccionar_perfil")

    error = None
    if perfil.is_locked():
        error = "Perfil bloqueado temporalmente. Intenta más tarde."
    elif request.method == "POST":
        raw_pin = request.POST.get("pin", "").strip()

        if not raw_pin.isdigit() or len(raw_pin) != 4:
            error = "El PIN debe ser de 4 dígitos numéricos."
        elif perfil.check_pin(raw_pin):
            perfil.intentos_fallidos = 0
            update = ["intentos_fallidos"]
            if perfil.bloqueado_hasta is not None:
                perfil.bloqueado_hasta = None
                update.append("bloqueado_hasta")
            perfil.save(update_fields=update)
            _registrar_bitacora(perfil, "PIN_OK",
                                f"PIN verificado para {perfil.nombre}.", request)
            request.session["perfil_id"] = perfil.pk
            request.session["ultima_actividad"] = timezone.now().isoformat()
            request.session.pop("perfil_activo", None)
            logger.info(f"PIN OK (local): {request.user.username} -> perfil {perfil.nombre}")
            return redirect(_destino_por_nivel(_nivel_cuenta(request.user, request)))
        else:
            perfil.intentos_fallidos = (perfil.intentos_fallidos or 0) + 1
            if perfil.intentos_fallidos >= MAX_INTENTOS:
                perfil.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=BLOQUEO_MINUTOS)
                perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
                _registrar_bitacora(perfil, "PERFIL_BLOQUEADO",
                                    f"{perfil.intentos_fallidos} intentos fallidos de PIN.", request)
                error = "Perfil bloqueado por intentos fallidos. Intenta más tarde."
            else:
                perfil.save(update_fields=["intentos_fallidos"])
                _registrar_bitacora(perfil, "PIN_FALLIDO",
                                    "Intento de PIN incorrecto.", request)
                restantes = MAX_INTENTOS - perfil.intentos_fallidos
                error = f"PIN incorrecto. Intentos restantes: {restantes}."

    return render(request, "cuentas/ingresar_pin.html", {
        "perfil": perfil,
        "error": error,
    })


# ─── Ingreso de PIN (local-primero, central como respaldo) ────────────────────

@login_required(login_url="cuentas:login")
def ingresar_pin(request, perfil_id):
    """
    Ruta 1 (preferida): el perfil existe en la BD local del usuario Y tiene
    PIN local (los PINs que asigna TI solo existen aquí).
    Ruta 2: perfil espejo sin PIN local (pin no utilizable) o solo-central →
    POST /api/permisos/verificar-pin/ y espejo local al éxito.
    """
    from django.contrib.auth.hashers import is_password_usable
    perfil_local = Perfil.objects.filter(pk=perfil_id, usuario=request.user).first()
    if perfil_local is not None and is_password_usable(perfil_local.pin_hash):
        return _ingresar_pin_local(request, perfil_local)

    if Perfil.objects.filter(pk=perfil_id).exclude(usuario=request.user).exists():
        # Existe pero es de otra cuenta: no revelar más.
        messages.error(request, "Ese perfil no pertenece a tu cuenta.")
        return redirect("cuentas:seleccionar_perfil")

    # ── Ruta 2: respaldo vía API Central (perfil no local) ──
    access_token = request.session.get("access_token", "")

    # Buscar el perfil en la sesión (ya cargado por seleccionar_perfil)
    perfiles_sesion = request.session.get("perfiles_disponibles", [])
    perfil_data = next((p for p in perfiles_sesion if str(p.get("id")) == str(perfil_id)), None)

    if not perfil_data:
        messages.error(request, "Perfil no encontrado. Selecciona uno de la lista.")
        return redirect("cuentas:seleccionar_perfil")

    # El espejo local conserva el ID central para verificar contra la API
    try:
        identidad_central = int(perfil_data.get("central_id") or perfil_id)
    except (TypeError, ValueError):
        identidad_central = perfil_id

    error = None

    if request.method == "POST":
        raw_pin = request.POST.get("pin", "").strip()

        if not raw_pin.isdigit() or len(raw_pin) != 4:
            error = "El PIN debe ser de 4 dígitos numéricos."
        else:
            # Validar PIN contra la API Central (con reintento si el access expiró)
            try:
                api_base = getattr(settings, "AUTH_SERVER_URL", "http://192.168.1.103:8000").rstrip("/")

                def _post_pin(token):
                    return http_requests.post(
                        f"{api_base}/api/permisos/verificar-pin/",
                        json={"identidad_id": identidad_central, "perfil_id": identidad_central, "pin": raw_pin},
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=5,
                    )

                resp = _post_pin(access_token)
                data = resp.json() if resp.content else {}

                if resp.status_code == 401 and request.session.get("refresh_token"):
                    # El access dura 5 min: intentar renovarlo una vez y reintentar
                    try:
                        r = http_requests.post(
                            f"{api_base}/api/permisos/token/refresh/",
                            json={"refresh": request.session["refresh_token"]},
                            timeout=5,
                        )
                        if r.status_code == 200 and r.json().get("access"):
                            request.session["access_token"] = r.json()["access"]
                            if r.json().get("refresh"):
                                request.session["refresh_token"] = r.json()["refresh"]
                            resp = _post_pin(request.session["access_token"])
                            data = resp.json() if resp.content else {}
                    except Exception as exc:
                        logger.warning(f"REFRESH TOKEN ERROR: {exc}")

                if resp.status_code == 200 and (data.get("ok") or data.get("status") == "OK"):
                    # PIN correcto — espejar la identidad central a Perfil local
                    # (el middleware y los vales solo entienden IDs locales).
                    espejo = _espejar_identidad_central(
                        request, identidad_central, perfil_data,
                        data.get("firma_url", ""), api_base, request.session.get("access_token", ""),
                    )
                    request.session["perfil_activo"] = perfil_data
                    request.session["perfil_id"] = espejo.pk if espejo else perfil_id
                    request.session["identidad_id"] = identidad_central
                    request.session["ultima_actividad"] = timezone.now().isoformat()
                    logger.info(f"PIN OK: {request.user.username} -> perfil {perfil_data.get('nombre')}")

                    # Routing inteligente por nivel
                    nivel = _nivel_cuenta(request.user, request)
                    return redirect(_destino_por_nivel(nivel))

                elif resp.status_code == 423:
                    # Perfil bloqueado por la API
                    error = data.get("error", "Perfil bloqueado. Contacta al administrador.")
                else:
                    error = data.get("error")
                    if not error:
                        intentos = data.get("intentos_restantes")
                        if intentos is not None:
                            error = f"PIN incorrecto. Intentos restantes: {intentos}."
                        else:
                            error = f"PIN incorrecto (la API devolvió estado {resp.status_code})."

            except Exception as exc:
                logger.error(f"ERROR verificar-pin API: {exc}")
                error = "No se pudo verificar el PIN. Intenta de nuevo."

    return render(request, "cuentas/ingresar_pin.html", {
        "perfil": perfil_data,
        "error": error,
    })


# ─── Cambio rápido de perfil ──────────────────────────────────────────────────

@login_required(login_url="cuentas:login")
def cambiar_perfil(request):
    perfil = getattr(request, "perfil_activo", None)
    if perfil:
        _registrar_bitacora(perfil, "CAMBIO_PERFIL", request=request)
    request.session.pop("perfil_id", None)
    request.session.pop("ultima_actividad", None)
    return redirect("cuentas:seleccionar_perfil")


# ─── Reautenticación con PIN (endpoint para modales HTMX) ────────────────────

def confirmar_pin_api(request):
    """Verifica el PIN del perfil activo. Usado por modales de acciones sensibles."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)

    perfil = getattr(request, "perfil_activo", None)
    if not perfil:
        return JsonResponse({"ok": False, "error": "Sin perfil activo."}, status=403)

    if perfil.is_locked():
        return JsonResponse({"ok": False, "error": "Perfil bloqueado."}, status=403)

    raw_pin = request.POST.get("pin", "")
    if not raw_pin.isdigit() or len(raw_pin) != 4:
        return JsonResponse({"ok": False, "error": "PIN inválido."}, status=400)

    if perfil.check_pin(raw_pin):
        perfil.intentos_fallidos = 0
        perfil.save(update_fields=["intentos_fallidos"])
        return JsonResponse({"ok": True})

    perfil.intentos_fallidos += 1
    if perfil.intentos_fallidos >= MAX_INTENTOS:
        perfil.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=BLOQUEO_MINUTOS)
        perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
        _registrar_bitacora(perfil, "PERFIL_BLOQUEADO", request=request)
        return JsonResponse({"ok": False, "error": "Perfil bloqueado por intentos fallidos."}, status=403)
    perfil.save(update_fields=["intentos_fallidos"])
    restantes = MAX_INTENTOS - perfil.intentos_fallidos
    return JsonResponse({"ok": False, "error": f"PIN incorrecto. Intentos restantes: {restantes}."}, status=400)


# ─── Vistas TI: gestión de cuentas (Nivel 6) ─────────────────────────────────

@nivel_requerido(6)
def ti_dashboard(request):
    """Panel principal de TI con contadores rápidos."""
    from app.almacen_vales.models import Vale, SolicitudAnulacion
    ctx = {
        "total_cuentas": User.objects.count(),
        "total_perfiles": Perfil.objects.count(),
        "vales_eliminados": Vale.all_objects.filter(eliminado=True).count(),
        "solicitudes_pendientes": SolicitudAnulacion.objects.filter(aprovada__isnull=True).count(),
        "ultimos_eventos": Bitacora.objects.select_related("perfil").order_by("-fecha")[:10],
    }
    return render(request, "almacen/ti/dashboard.html", ctx)


@nivel_requerido(6)
def ti_cuentas_list(request):
    qs = User.objects.select_related("extension").order_by("username")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(username__icontains=q)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    form = CuentaCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        _registrar_bitacora(
            request.perfil_activo,
            "TI_CUENTA_CREADA",
            f"Usuario: {user.username}",
            request,
        )
        messages.success(request, f"Cuenta «{user.username}» creada correctamente.")
        return redirect("cuentas:ti_cuentas")
    return render(request, "almacen/ti/cuentas_list.html", {
        "page_obj": page_obj, "form": form, "q": q,
    })


@nivel_requerido(6)
def ti_cuenta_editar(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    ext, _ = CuentaExtension.objects.get_or_create(usuario=user)
    initial = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "nivel": ext.nivel,
        "is_active": user.is_active,
    }
    form = CuentaEditForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save(user)
        _registrar_bitacora(
            request.perfil_activo,
            "TI_CUENTA_EDITADA",
            f"Usuario: {user.username}",
            request,
        )
        messages.success(request, "Cuenta actualizada.")
        return redirect("cuentas:ti_cuentas")
    return render(request, "almacen/ti/cuenta_form.html", {
        "form": form, "cuenta": user,
    })


@nivel_requerido(6)
def ti_perfiles_list(request, user_id):
    cuenta = get_object_or_404(User, pk=user_id)
    perfiles = Perfil.objects.filter(usuario=cuenta).order_by("nombre")
    return render(request, "almacen/ti/perfiles_list.html", {
        "cuenta": cuenta, "perfiles": perfiles,
    })


@nivel_requerido(6)
def ti_perfil_crear(request, user_id):
    cuenta = get_object_or_404(User, pk=user_id)
    form = PerfilForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        perfil = form.save(commit=False)
        perfil.usuario = cuenta
        perfil.pin_hash = ""  # Se establecerá después con ti_perfil_pin
        perfil.save()
        _registrar_bitacora(
            request.perfil_activo,
            "TI_PERFIL_CREADO",
            f"Perfil: {perfil.nombre} para cuenta: {cuenta.username}",
            request,
        )
        messages.success(request, f"Perfil «{perfil.nombre}» creado. Asigna el PIN a continuación.")
        return redirect("cuentas:ti_perfil_pin", perfil_id=perfil.pk)
    return render(request, "almacen/ti/perfil_form.html", {
        "form": form, "cuenta": cuenta, "titulo": "Nuevo perfil",
    })


@nivel_requerido(6)
def ti_perfil_editar(request, perfil_id):
    perfil = get_object_or_404(Perfil, pk=perfil_id)
    form = PerfilForm(request.POST or None, request.FILES or None, instance=perfil)
    if request.method == "POST" and form.is_valid():
        form.save()
        _registrar_bitacora(
            request.perfil_activo,
            "TI_PERFIL_EDITADO",
            f"Perfil: {perfil.nombre}",
            request,
        )
        messages.success(request, "Perfil actualizado.")
        return redirect("cuentas:ti_perfiles", user_id=perfil.usuario_id)
    return render(request, "almacen/ti/perfil_form.html", {
        "form": form, "cuenta": perfil.usuario, "titulo": f"Editar — {perfil.nombre}",
    })


@nivel_requerido(6)
def ti_perfil_pin(request, perfil_id):
    """Asigna o restablece el PIN de un perfil."""
    perfil = get_object_or_404(Perfil, pk=perfil_id)
    form = PerfilPINForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        perfil.set_pin(form.cleaned_data["nuevo_pin"])
        perfil.intentos_fallidos = 0
        perfil.bloqueado_hasta = None
        perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
        _registrar_bitacora(
            request.perfil_activo,
            "TI_PIN_RESTABLECIDO",
            f"Perfil: {perfil.nombre}",
            request,
        )
        messages.success(request, f"PIN de «{perfil.nombre}» actualizado correctamente.")
        return redirect("cuentas:ti_perfiles", user_id=perfil.usuario_id)
    return render(request, "almacen/ti/perfil_pin.html", {
        "form": form, "perfil": perfil,
    })


@nivel_requerido(6)
def ti_perfil_toggle(request, perfil_id):
    """Activa / desactiva un perfil."""
    perfil = get_object_or_404(Perfil, pk=perfil_id)
    perfil.activo = not perfil.activo
    perfil.save(update_fields=["activo"])
    estado = "activado" if perfil.activo else "desactivado"
    _registrar_bitacora(
        request.perfil_activo,
        "TI_PERFIL_TOGGLE",
        f"Perfil {perfil.nombre} {estado}",
        request,
    )
    messages.info(request, f"Perfil «{perfil.nombre}» {estado}.")
    return redirect("cuentas:ti_perfiles", user_id=perfil.usuario_id)


# ─── Vista protegida de firmas ────────────────────────────────────────────────

_EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _servir_imagen_privada(path):
    """Devuelve una imagen de MEDIA_ROOT sin permitir salir de esa carpeta.

    Solo acepta extensiones de imagen (bloquea .py/.db/.env, etc.).
    """
    if not path.lower().endswith(_EXTENSIONES_IMAGEN):
        raise Http404

    base = Path(settings.MEDIA_ROOT).resolve()
    full_path = (base / path).resolve()
    try:
        full_path.relative_to(base)
    except ValueError:
        raise Http404
    if not full_path.is_file():
        raise Http404

    mime, _ = mimetypes.guess_type(str(full_path))
    resp = FileResponse(open(full_path, "rb"), content_type=mime or "image/png")
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def serve_firma(request, path):
    """
    Sirve imágenes de firmas de forma privada.
    Solo usuarios autenticados con nivel >= 3 (o el mismo nivel 1 si es su propio vale).
    Anti-traversal: confina a MEDIA_ROOT y solo extensiones de imagen.
    """
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    try:
        nivel = request.user.extension.nivel
    except Exception:
        raise Http404
    if nivel < 3 and not request.user.is_superuser:
        raise Http404

    return _servir_imagen_privada(path)


def serve_media_protegida(request, path):
    """Puerta /media/ en producción (DEBUG=False).
    Cualquier usuario autenticado (los avatares los ven niveles 1-6).
    Anónimos -> login. Anti-traversal + solo imágenes."""
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    return _servir_imagen_privada(path)
