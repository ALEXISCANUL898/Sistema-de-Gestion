from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import transaction
from django.core.files.base import ContentFile
from django.conf import settings
from django.contrib.auth.hashers import is_password_usable
from decimal import Decimal, InvalidOperation
import requests as http_requests

from app.cuentas.decorators import login_perfil_requerido, nivel_requerido
from app.cuentas.models import Perfil
from app.auditoria.models import Bitacora
from app.catalogos.models import Empresa, Area, Plano, Material, Unidad, Configuracion
from .models import Vale, SolicitudAnulacion, DetalleVale, AsignacionVale, FirmaSnapshot, Entrega, DetalleEntrega

MAX_INTENTOS = getattr(settings, "PIN_MAX_INTENTOS", 5)
BLOQUEO_MINUTOS = getattr(settings, "PIN_BLOQUEO_MINUTOS", 15)

# ── Helpers ──
def _registrar_bitacora(perfil, accion, detalle, request):
    ip = request.META.get("REMOTE_ADDR", "")
    Bitacora.objects.create(perfil=perfil, accion=accion, detalle=detalle, ip=ip)

def _nivel(request):
    try:
        return int(request.user.extension.nivel)
    except Exception:
        pass
    # Respaldo: sesión central (cuentas espejo sin extensión sincronizada)
    for k in ("permiso_Almacen", "permiso_Catalogos", "permiso_Auditoria"):
        try:
            n = int((request.session.get(k) or {}).get("nivel_acceso", 0))
            if n:
                return n
        except Exception:
            continue
    return 0

def _perfil_o_selector(request):
    """Devuelve el perfil activo o None (con mensaje) si la sesión expiró."""
    perfil = getattr(request, "perfil_activo", None)
    if perfil is None:
        messages.error(request, "Tu sesión de perfil expiró. Selecciónalo de nuevo.")
    return perfil

def _es_solicitante(request):
    return _nivel(request) == 1 or request.user.is_superuser

def _ctx_catalogos():
    cfg = Configuracion.get_solo()
    return {
        "empresas": Empresa.objects.filter(activa=True),
        "areas": Area.objects.filter(activa=True),
        "planos": Plano.objects.filter(activa=True),
        "unidades": Unidad.objects.filter(activa=True),
        "materiales": Material.objects.filter(activa=True).select_related("unidad_sugerida"),
        "max_filas": cfg.max_filas_vale or 12,
        "movimientos": Vale.TIPOS_MOVIMIENTO,
    }

def _parse_filas(post, max_filas):
    """Lee las filas material_id[]/cantidad[]/unidad[] del POST (catálogo por folio).
    Devuelve (filas, errores). filas = [{material(obj), cantidad, unidad}].
    Catálogos en 2 queries (in_bulk), no 2N."""
    mids = post.getlist("material_id[]")
    cants = post.getlist("cantidad[]")
    unids = post.getlist("unidad[]")
    filas, errores = [], []
    vistos = set()
    _mid_ids, _uni_ids = set(), set()
    for i in range(max(len(mids), len(cants), len(unids))):
        mid_raw = (mids[i] if i < len(mids) else "").strip()
        uni_raw = (unids[i] if i < len(unids) else "").strip()
        if str(mid_raw).isdigit():
            _mid_ids.add(int(mid_raw))
        if str(uni_raw).isdigit():
            _uni_ids.add(int(uni_raw))
    _mats = Material.objects.in_bulk(_mid_ids) if _mid_ids else {}
    _unis = Unidad.objects.in_bulk(_uni_ids) if _uni_ids else {}
    for i in range(max(len(mids), len(cants), len(unids))):
        mid_raw = (mids[i] if i < len(mids) else "").strip()
        cant_raw = (cants[i] if i < len(cants) else "").strip()
        uni_raw = (unids[i] if i < len(unids) else "").strip()
        if not mid_raw and not cant_raw and not uni_raw:
            continue  # fila vacía
        n = i + 1
        mat = _mats.get(int(mid_raw)) if str(mid_raw).isdigit() else None
        if mat is None or not mat.activa:
            errores.append(f"Fila {n}: busca y selecciona un material del catálogo.")
            continue
        if mat.pk in vistos:
            errores.append(f"Fila {n}: el material {mat.folio} está repetido.")
            continue
        vistos.add(mat.pk)
        try:
            cant = Decimal(cant_raw.replace(",", "."))
        except (InvalidOperation, AttributeError):
            errores.append(f"Fila {n}: cantidad inválida.")
            continue
        if cant <= 0:
            errores.append(f"Fila {n}: la cantidad debe ser mayor a 0.")
            continue
        try:
            unidad = _unis.get(int(uni_raw)) if str(uni_raw).isdigit() else None
            if unidad is None or not unidad.activa:
                raise ValueError
        except (ValueError, TypeError):
            errores.append(f"Fila {n}: unidad inválida.")
            continue
        filas.append({"material": mat, "cantidad": cant, "unidad": unidad})
    if len(filas) > max_filas:
        errores.append(f"Máximo {max_filas} materiales por vale.")
    if not filas and not errores:
        errores.append("Agrega al menos un material del catálogo.")
    return filas, errores

def _leer_datos_vale(post):
    """Lee y valida los datos generales del formulario del vale."""
    datos = {
        "tipo_movimiento": post.get("tipo_movimiento", "Salida de material"),
        "tipo_detalle": post.get("tipo_detalle", "").strip()[:100],
        "empresa_id": post.get("empresa", ""),
        "area_id": post.get("area", ""),
        "plano_id": post.get("plano", ""),
        "dato_otro": post.get("dato_otro", "").strip()[:255],
        "notas": post.get("notas", "").strip(),
    }
    if datos["tipo_movimiento"] not in dict(Vale.TIPOS_MOVIMIENTO):
        datos["tipo_movimiento"] = "Salida de material"
    errores = []
    if datos["tipo_movimiento"] == "Otro" and not datos["tipo_detalle"]:
        errores.append("Especifica el tipo de movimiento (Otro).")
    if not datos["empresa_id"] or not Empresa.objects.filter(pk=datos["empresa_id"], activa=True).exists():
        errores.append("Selecciona la empresa (obligatorio).")
    if not datos["area_id"] or not Area.objects.filter(pk=datos["area_id"], activa=True).exists():
        errores.append("Selecciona el área (obligatorio).")
    if not datos["plano_id"] or not Plano.objects.filter(pk=datos["plano_id"], activa=True).exists():
        errores.append("Selecciona el plano (obligatorio).")
    return datos, errores

def _crear_detalles(vale, filas):
    DetalleVale.objects.bulk_create([
        DetalleVale(
            vale=vale,
            material=f["material"],
            cantidad_solicitada=f["cantidad"],
            unidad=f["unidad"],
        )
        for f in filas
    ])

def _filas_desde_raw(post):
    """Reconstruye las filas para re-renderizar el formulario tras un error,
    resolviendo folio/descripción desde el catálogo (1 query)."""
    triples = list(zip(post.getlist("material_id[]"),
                       post.getlist("cantidad[]"),
                       post.getlist("unidad[]")))
    _ids = {int(m) for m, _, _ in triples if str(m).isdigit()}
    _map = Material.objects.in_bulk(_ids) if _ids else {}
    out = []
    for mid, cant, uni in triples:
        m = _map.get(int(mid)) if str(mid).isdigit() else None
        out.append({"material_id": mid or "", "folio": m.folio if m else "",
                    "material": m.descripcion if m else "",
                    "cantidad": cant or "", "unidad_id": uni or ""})
    return out

# ── Solicitante (Nivel 1) ───────────────────────────────────────────────────

@login_perfil_requerido
@nivel_requerido(1)
def mis_vales_list(request):
    from django.db.models import Count
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    base = Vale.objects.filter(creado_por=perfil)

    q = request.GET.get("q", "").strip()
    if q:
        base = base.filter(consecutivo__icontains=q)

    TABS = {
        "activos": ("Activos", ("BORRADOR", "EMITIDO", "ASIGNADO", "PARCIAL", "POR_CERRAR")),
        "borradores": ("Borradores", ("BORRADOR",)),
        "emitidos": ("Emitidos", ("EMITIDO",)),
        "proceso": ("En proceso", ("ASIGNADO", "PARCIAL")),
        "por_cerrar": ("Por cerrar", ("POR_CERRAR",)),
        "cerrados": ("Cerrados", ("CERRADO",)),
        "faltante": ("C. faltante", ("CERRADO_CON_FALTANTE",)),
    }
    tab_estado = request.GET.get("tab_estado", "activos")
    if tab_estado not in TABS:
        tab_estado = "activos"
    qs = base.filter(estado__in=TABS[tab_estado][1]).order_by("-fecha")

    conteo = dict(base.values("estado").annotate(n=Count("id")).values_list("estado", "n"))
    tabs = [(k, label, sum(conteo.get(e, 0) for e in estados)) for k, (label, estados) in TABS.items()]

    qd = request.GET.copy()
    qd.pop("page", None)
    qs_page = qd.urlencode()

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "almacen/solicitante/mis_vales.html", {
        "page_obj": page_obj, "q": q, "tab_estado": tab_estado,
        "tabs_estado": tabs, "qs_page": qs_page,
    })

@login_perfil_requerido
@nivel_requerido(1)
def vale_create(request):
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_solicitante(request):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    ctx = _ctx_catalogos()
    ctx["perfil"] = perfil
    ctx["hoy"] = timezone.localdate()

    if request.method == "POST":
        datos, err_mov = _leer_datos_vale(request.POST)
        filas, errores = _parse_filas(request.POST, ctx["max_filas"])
        errores = err_mov + errores

        if errores:
            for e in errores:
                messages.error(request, e)
            ctx.update(datos)
            ctx["filas_json"] = [
                {"material_id": f["material"].pk, "folio": f["material"].folio,
                 "material": f["material"].descripcion,
                 "cantidad": str(f["cantidad"]), "unidad_id": f["unidad"].pk}
                for f in filas
            ] or _filas_desde_raw(request.POST)
            return render(request, "almacen/solicitante/vale_create.html", ctx)

        with transaction.atomic():
            vale = Vale.objects.create(
                creado_por=perfil,
                estado="BORRADOR",
                tipo_movimiento=datos["tipo_movimiento"],
                tipo_detalle=datos["tipo_detalle"] if datos["tipo_movimiento"] == "Otro" else "",
                empresa_id=datos["empresa_id"] or None,
                area_id=datos["area_id"] or None,
                plano_id=datos["plano_id"] or None,
                dato_otro=datos["dato_otro"],
                notas=datos["notas"],
            )
            _crear_detalles(vale, filas)
        _registrar_bitacora(perfil, "VALE_BORRADOR", f"Borrador {vale.pk} creado ({len(filas)} líneas).", request)
        messages.success(request, "Borrador guardado. Revísalo y fírmalo para emitirlo.")
        return redirect("almacen:vale_detalle", pk=vale.pk)

    return render(request, "almacen/solicitante/vale_create.html", ctx)

@login_perfil_requerido
@nivel_requerido(1)
@require_POST
def vale_create_emitir(request):
    """Crea y emite en un solo paso: valida, verifica PIN, estampa RETIRADO,
    asigna consecutivo y deja el vale EMITIDO. Todo o nada."""
    from django.core.exceptions import PermissionDenied
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_solicitante(request):
        raise PermissionDenied
    ctx = _ctx_catalogos()
    ctx["perfil"] = perfil

    datos, err_mov = _leer_datos_vale(request.POST)
    filas, errores = _parse_filas(request.POST, ctx["max_filas"])
    errores = err_mov + errores
    pin = (request.POST.get("pin", "") or "").strip()
    pin_error = None
    if not pin.isdigit() or len(pin) != 4:
        pin_error = "Escribe tu PIN de 4 dígitos para enviarlo a almacén."

    def _reintentar():
        for e in errores:
            messages.error(request, e)
        if pin_error:
            messages.error(request, pin_error)
        ctx.update(datos)
        ctx["filas_json"] = _filas_desde_raw(request.POST)
        ctx["pin_error"] = pin_error
        ctx["abrir_destino"] = bool(pin_error)
        return render(request, "almacen/solicitante/vale_create.html", ctx)

    if errores or pin_error:
        return _reintentar()

    ok, msg = _verificar_pin_operador(perfil, pin, request, "emisión directa")
    if not ok:
        pin_error = msg
        messages.error(request, msg)
        ctx.update(datos)
        ctx["filas_json"] = _filas_desde_raw(request.POST)
        ctx["pin_error"] = pin_error
        ctx["abrir_destino"] = True
        return render(request, "almacen/solicitante/vale_create.html", ctx)

    if not getattr(perfil, "firma", None):
        messages.error(request, "Tu perfil no tiene firma cargada. Pide a TI que la registre.")
        return _reintentar()

    with transaction.atomic():
        vale = Vale.objects.create(
            creado_por=perfil,
            estado="BORRADOR",
            tipo_movimiento=datos["tipo_movimiento"],
            tipo_detalle=datos["tipo_detalle"] if datos["tipo_movimiento"] == "Otro" else "",
            empresa_id=datos["empresa_id"] or None,
            area_id=datos["area_id"] or None,
            plano_id=datos["plano_id"] or None,
            dato_otro=datos["dato_otro"],
            notas=datos["notas"],
        )
        _crear_detalles(vale, filas)
        snap = _snapshot_firma(vale, "RETIRADO", perfil)
        if snap is None:
            transaction.set_rollback(True)
            messages.error(request, "Tu firma no es una imagen válida. Pide a TI que la actualice.")
            return _reintentar()
        vale.asignar_consecutivo()
        vale.estado = "EMITIDO"
        vale.save(update_fields=["consecutivo", "estado"])
    _registrar_bitacora(perfil, "VALE_EMITIDO",
                        f"Vale N° {vale.consecutivo} creado y emitido en un paso.", request)
    messages.success(request, f"Vale N° {vale.consecutivo} enviado a almacén.")
    return redirect("almacen:vale_detalle", pk=vale.pk)

@login_perfil_requerido
@nivel_requerido(1)
def vale_editar(request, pk):
    from django.core.exceptions import PermissionDenied
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_solicitante(request):
        raise PermissionDenied
    vale = get_object_or_404(Vale, pk=pk, creado_por=perfil, estado="BORRADOR")
    ctx = _ctx_catalogos()
    ctx["perfil"] = perfil
    ctx["vale"] = vale

    if request.method == "POST":
        datos, err_mov = _leer_datos_vale(request.POST)
        filas, errores = _parse_filas(request.POST, ctx["max_filas"])
        errores = err_mov + errores
        if errores:
            for e in errores:
                messages.error(request, e)
            ctx.update(datos)
            ctx["filas_json"] = _filas_desde_raw(request.POST)
            return render(request, "almacen/solicitante/vale_create.html", ctx)
        with transaction.atomic():
            vale.tipo_movimiento = datos["tipo_movimiento"]
            vale.tipo_detalle = datos["tipo_detalle"] if datos["tipo_movimiento"] == "Otro" else ""
            vale.empresa_id = datos["empresa_id"] or None
            vale.area_id = datos["area_id"] or None
            vale.plano_id = datos["plano_id"] or None
            vale.dato_otro = datos["dato_otro"]
            vale.notas = datos["notas"]
            vale.save()
            vale.detalles.all().delete()
            _crear_detalles(vale, filas)
        _registrar_bitacora(perfil, "VALE_BORRADOR_EDITADO", f"Borrador {vale.pk} editado.", request)
        messages.success(request, "Borrador actualizado.")
        return redirect("almacen:vale_detalle", pk=vale.pk)

    ctx.update({
        "tipo_movimiento": vale.tipo_movimiento,
        "tipo_detalle": vale.tipo_detalle,
        "empresa_id": str(vale.empresa_id or ""),
        "area_id": str(vale.area_id or ""),
        "plano_id": str(vale.plano_id or ""),
        "dato_otro": vale.dato_otro,
        "notas": vale.notas,
        "filas_json": [
            {"material_id": d.material_id, "folio": d.material.folio,
             "material": d.material.descripcion,
             "cantidad": str(d.cantidad_solicitada), "unidad_id": d.unidad_id}
            for d in vale.detalles.select_related("material", "unidad")
        ],
    })
    return render(request, "almacen/solicitante/vale_create.html", ctx)

@login_perfil_requerido
@nivel_requerido(1)
@require_POST
def vale_descartar(request, pk):
    from django.core.exceptions import PermissionDenied
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_solicitante(request):
        raise PermissionDenied
    vale = get_object_or_404(Vale, pk=pk, creado_por=perfil, estado="BORRADOR")
    vale.delete()  # borrador sin consecutivo: borrado físico permitido
    _registrar_bitacora(perfil, "VALE_BORRADOR_DESCARTADO", f"Borrador {pk} descartado.", request)
    messages.info(request, "Borrador descartado.")
    return redirect("almacen:mis_vales")

@login_perfil_requerido
@nivel_requerido(1)
def vale_detalle(request, pk):
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    vale = get_object_or_404(Vale, pk=pk)

    # Validation to only see their own vales, unless higher level
    nivel = _nivel(request)
    if nivel < 3 and vale.creado_por_id != perfil.pk:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    detalles = vale.detalles.select_related("material", "unidad")
    entregas = vale.entregas.select_related("perfil").prefetch_related("detalles__detalle_vale__material")
    firmas = vale.firmas.all()
    solicitud_pendiente = vale.solicitudes_anulacion.filter(aprovada__isnull=True).first()
    es_dueno = perfil is not None and vale.creado_por_id == perfil.pk
    return render(request, "almacen/solicitante/vale_detalle.html", {
        "vale": vale,
        "detalles": detalles,
        "entregas": entregas,
        "firmas": firmas,
        "firmas_dos": [f for f in firmas if f.tipo in ("RETIRADO", "DESPACHADO")],
        "puede_operar": es_dueno and _es_solicitante(request),
        "solicitud_pendiente": solicitud_pendiente,
    })

@login_perfil_requerido
@nivel_requerido(1)
@require_POST
def vale_firmar(request, pk):
    """Firma del solicitante (RETIRADO POR) con PIN: asigna consecutivo y EMITE.
    Snapshot inmutable de nombre, puesto y firma del perfil."""
    from django.core.exceptions import PermissionDenied
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_solicitante(request):
        raise PermissionDenied
    vale = get_object_or_404(Vale, pk=pk, creado_por=perfil, estado="BORRADOR")

    ok, msg = _verificar_pin_operador(perfil, request.POST.get("pin", "").strip(), request, "firma de vale")
    if not ok:
        messages.error(request, msg)
        return redirect("almacen:vale_detalle", pk=pk)

    if not vale.detalles.exists():
        messages.error(request, "El vale no tiene materiales. Edítalo antes de firmarlo.")
        return redirect("almacen:vale_detalle", pk=pk)

    with transaction.atomic():
        # Snapshot inmutable de la firma (copia del archivo del perfil)
        snap = FirmaSnapshot(vale=vale, tipo="RETIRADO", nombre=perfil.nombre, puesto=perfil.puesto)
        if perfil.firma:
            try:
                with perfil.firma.open("rb") as f:
                    snap.firma.save(f"retirado_v{vale.pk}_p{perfil.pk}.png", ContentFile(f.read()), save=False)
            except Exception:
                pass
        if not snap.firma:
            messages.error(request, "Tu perfil no tiene firma cargada. Pide a TI que la registre.")
            return redirect("almacen:vale_detalle", pk=pk)
        snap.save()
        # Consecutivo + emisión (todo o nada)
        vale.asignar_consecutivo()
        vale.estado = "EMITIDO"
        vale.save(update_fields=["consecutivo", "estado"])
        perfil.intentos_fallidos = 0
        perfil.bloqueado_hasta = None
        perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])

    _registrar_bitacora(perfil, "VALE_EMITIDO", f"Vale N° {vale.consecutivo} emitido.", request)
    messages.success(request, f"Vale N° {vale.consecutivo} emitido y enviado a almacén.")
    return redirect("almacen:vale_detalle", pk=pk)

@login_perfil_requerido
@nivel_requerido(1)
@require_POST
def solicitud_anulacion(request, pk):
    """Solicita la anulación de un vale emitido (lo resuelve TI)."""
    from django.core.exceptions import PermissionDenied
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_solicitante(request):
        raise PermissionDenied
    vale = get_object_or_404(Vale, pk=pk, creado_por=perfil)
    if vale.estado == "BORRADOR":
        messages.error(request, "Es un borrador: edítalo o descártalo en lugar de anularlo.")
        return redirect("almacen:vale_detalle", pk=pk)
    if vale.solicitudes_anulacion.filter(aprovada__isnull=True).exists():
        messages.warning(request, "Ya tienes una solicitud de anulación pendiente para este vale.")
        return redirect("almacen:vale_detalle", pk=pk)
    motivo = request.POST.get("motivo", "").strip()
    if len(motivo) < 10:
        messages.error(request, "El motivo debe tener al menos 10 caracteres.")
        return redirect("almacen:vale_detalle", pk=pk)
    SolicitudAnulacion.objects.create(vale=vale, solicitante=perfil, motivo=motivo)
    _registrar_bitacora(perfil, "ANULACION_SOLICITADA",
                        f"Vale {vale.consecutivo or vale.pk}: {motivo[:120]}", request)
    messages.success(request, "Solicitud de anulación enviada a TI.")
    return redirect("almacen:vale_detalle", pk=pk)

# ── Almacén (Nivel 3): bandeja, asignación, despacho y cierre ────────────────

ESTADOS_OPERABLES = ("EMITIDO", "ASIGNADO", "PARCIAL")
ESTADOS_FINALES = ("CERRADO", "CERRADO_CON_FALTANTE", "PRESTAMO_ABIERTO", "ANULADO")

def _rol_almacen(request):
    perfil = getattr(request, "perfil_activo", None)
    return perfil.rol_almacen if perfil else None

def _es_encargado(request):
    return request.user.is_superuser or _rol_almacen(request) == "ENCARGADO"

def _asignacion_vigente(vale):
    return vale.asignaciones.filter(vigente=True).select_related("asignado_a", "asignado_por").first()

def _puede_operar(request, vale):
    """Solo el encargado registra entregas en el sistema: el despachador
    entrega en físico y reporta en papel; el asignado vigente queda como
    referencia de quién hizo la entrega física.
    Requiere que el vale tenga despachador asignado."""
    perfil = getattr(request, "perfil_activo", None)
    if perfil is None or vale.estado not in ESTADOS_OPERABLES:
        return False
    if not (request.user.is_superuser or _es_encargado(request)):
        return False
    return _asignacion_vigente(vale) is not None

def _puede_cerrar(request):
    """El cierre (normal o con faltante) es exclusivo del encargado."""
    return request.user.is_superuser or _es_encargado(request)

def _recalcular_estado(vale):
    if vale.estado in ESTADOS_FINALES or vale.estado == "BORRADOR":
        return vale.estado
    dets = list(vale.detalles.all())
    if not dets:
        return vale.estado
    if all(d.cantidad_entregada >= d.cantidad_solicitada for d in dets):
        return "POR_CERRAR"
    if any(d.cantidad_entregada > 0 for d in dets):
        return "PARCIAL"
    return "ASIGNADO" if _asignacion_vigente(vale) else "EMITIDO"

def _verificar_pin_central(perfil, raw_pin, request):
    """Verifica el PIN contra el Control de Usuario (espejos sin PIN local).
    El central lleva su propio conteo de intentos y bloqueo."""
    token = request.session.get("access_token", "")
    if not token:
        return False, "Sin sesión central. Sal y entra de nuevo."
    api_base = getattr(settings, "AUTH_SERVER_URL", "http://192.168.1.103:8000").rstrip("/")
    try:
        resp = http_requests.post(
            f"{api_base}/api/permisos/verificar-pin/",
            json={"identidad_id": perfil.central_id, "pin": raw_pin},
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        data = resp.json() if resp.content else {}
    except Exception:
        return False, "No se pudo verificar el PIN con el central. Intenta de nuevo."
    if resp.status_code == 200 and (data.get("ok") or data.get("status") == "OK"):
        perfil.intentos_fallidos = 0
        perfil.bloqueado_hasta = None
        perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
        # Si la firma cambió en el central, sincronizarla
        try:
            from app.cuentas.views import sincronizar_firma_espejo
            sincronizar_firma_espejo(
                perfil, data.get("firma_url", ""),
                getattr(settings, "AUTH_SERVER_URL", "http://192.168.1.103:8000"),
                request.session.get("access_token", ""),
            )
        except Exception:
            pass
        return True, ""
    if resp.status_code == 423:
        return False, data.get("error", "Perfil bloqueado en el central. Intenta más tarde.")
    return False, data.get("error", "PIN incorrecto.")

def _verificar_pin_operador(perfil, raw_pin, request, contexto=""):
    """Reautenticación con PIN para acciones sensibles (con bloqueo)."""
    if perfil.is_locked():
        return False, "Tu perfil está bloqueado temporalmente. Intenta más tarde."
    if not (raw_pin or "").isdigit() or len((raw_pin or "")) != 4:
        return False, "El PIN debe ser de 4 dígitos numéricos."
    # Espejo sin PIN local → el PIN vive en el central
    if not is_password_usable(perfil.pin_hash or "") and getattr(perfil, "central_id", None):
        return _verificar_pin_central(perfil, raw_pin, request)
    if perfil.check_pin(raw_pin):
        perfil.intentos_fallidos = 0
        upd = ["intentos_fallidos"]
        if perfil.bloqueado_hasta is not None:
            perfil.bloqueado_hasta = None
            upd.append("bloqueado_hasta")
        perfil.save(update_fields=upd)
        return True, ""
    perfil.intentos_fallidos = (perfil.intentos_fallidos or 0) + 1
    if perfil.intentos_fallidos >= MAX_INTENTOS:
        perfil.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=BLOQUEO_MINUTOS)
        perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
        _registrar_bitacora(perfil, "PERFIL_BLOQUEADO", f"Bloqueo: {contexto}", request)
        return False, "PIN incorrecto. Perfil bloqueado por intentos fallidos."
    perfil.save(update_fields=["intentos_fallidos"])
    return False, f"PIN incorrecto. Intentos restantes: {MAX_INTENTOS - perfil.intentos_fallidos}."

def _bytes_son_imagen(data):
    """True si los bytes son una imagen real (PNG/JPEG/GIF/WEBP)."""
    if not data or len(data) < 16:
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

def _snapshot_firma(vale, tipo, perfil):
    """Snapshot inmutable; devuelve el snapshot o None si no hay imagen válida."""
    snap = FirmaSnapshot(vale=vale, tipo=tipo, nombre=perfil.nombre, puesto=perfil.puesto)
    if getattr(perfil, "firma", None):
        try:
            with perfil.firma.open("rb") as f:
                data = f.read()
            if _bytes_son_imagen(data):
                snap.firma.save(f"{tipo.lower()}_v{vale.pk}_p{perfil.pk}.png",
                                ContentFile(data), save=False)
        except Exception:
            pass
    if snap.firma:
        snap.save()
        return snap
    return None

def _sincronizar_espejos_almacen(request):
    """Crea/actualiza espejos locales de todas las identidades centrales del
    sistema 004. Así el encargado puede asignar despachadores que aún no han
    entrado nunca. Nunca rompe la vista si el central no responde."""
    try:
        from app.cuentas.views import _espejar_identidad_central
    except Exception:
        return 0
    token = request.session.get("access_token", "")
    if not token:
        return 0
    sistema = request.session.get("permiso_Almacen", {}).get("sistema_codigo", "004")
    api_base = getattr(settings, "AUTH_SERVER_URL", "http://192.168.1.103:8000").rstrip("/")
    try:
        resp = http_requests.get(
            f"{api_base}/api/permisos/mis-identidades/",
            params={"sistema": sistema},
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code != 200:
            return 0
        raw = resp.json()
        if not isinstance(raw, list):
            return 0
        n = 0
        for p in raw:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            p["nombre"] = p.get("nombre_completo", p.get("nombre", ""))
            p["rol_almacen"] = p.get("rol_almacen") or p.get("rol_nombre", "")
            if _espejar_identidad_central(request, p.get("id"), p, "", api_base, token):
                n += 1
        return n
    except Exception:
        return 0


def _semaforo(vale, cfg, vigente):
    base = vigente.fecha if vigente else vale.fecha
    try:
        horas = (timezone.now() - base).total_seconds() / 3600
    except Exception:
        return "verde", 0
    if horas >= (cfg.semaforo_rojo_horas or 4):
        return "rojo", round(horas, 1)
    if horas >= (cfg.semaforo_amarillo_horas or 2):
        return "amarillo", round(horas, 1)
    return "verde", round(horas, 1)

def _rango_dias(desde_d, hasta_d):
    """Rango aware (UTC) para filtrar DateTimes por días locales.
    Evita __date, que exige tablas de zona horaria en MySQL."""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    zona = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
    return (datetime.combine(desde_d, time.min).replace(tzinfo=zona),
            datetime.combine(hasta_d, time.max).replace(tzinfo=zona))

@login_perfil_requerido
@nivel_requerido(3)
def bandeja_almacen(request):
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    encargado = _es_encargado(request)
    cfg = Configuracion.get_solo()
    if encargado:
        # Espeja despachadores nuevos para poder asignarles aunque no hayan entrado
        _sincronizar_espejos_almacen(request)

    # ── Asignación masiva (encargado) ──
    if request.method == "POST" and encargado:
        ids = [i for i in request.POST.getlist("vale_ids") if str(i).isdigit()]
        desp_id = request.POST.get("despachador_id", "")
        if not ids or not desp_id.isdigit():
            messages.error(request, "Selecciona al menos un vale y un despachador.")
            return redirect("almacen:bandeja")
        _asignar_vales(request, perfil, ids, int(desp_id), "")
        return redirect("almacen:bandeja")

    qs = Vale.objects.exclude(estado="BORRADOR").select_related(
        "empresa", "area", "plano", "creado_por").order_by("-fecha")
    tab = request.GET.get("tab", "mis" if not encargado else "todos")

    # Filtros
    q = request.GET.get("q", "").strip()
    tab_estado = request.GET.get("tab_estado", "todos")
    f_empresa = request.GET.get("empresa", "")
    f_area = request.GET.get("area", "")
    f_plano = request.GET.get("plano", "")
    f_solic = request.GET.get("solicitante", "").strip()
    f_desp = request.GET.get("despachador", "")
    f_tipo = request.GET.get("tipo", "")
    f_desde = request.GET.get("desde", "")
    f_hasta = request.GET.get("hasta", "")
    TABS_ESTADO = {
        "activos": ("EMITIDO", "ASIGNADO", "PARCIAL", "POR_CERRAR"),
        "por_asignar": ("EMITIDO",),
        "asignados": ("ASIGNADO",),
        "parciales": ("PARCIAL",),
        "por_cerrar": ("POR_CERRAR",),
        "cerrados": ("CERRADO",),
        "faltante": ("CERRADO_CON_FALTANTE",),
        "prestamos": ("PRESTAMO_ABIERTO",),
    }
    if tab_estado not in TABS_ESTADO:
        tab_estado = "activos"
    if q:
        qs = qs.filter(consecutivo__icontains=q)
    qs = qs.filter(estado__in=TABS_ESTADO[tab_estado])
    if f_empresa.isdigit():
        qs = qs.filter(empresa_id=int(f_empresa))
    if f_area.isdigit():
        qs = qs.filter(area_id=int(f_area))
    if f_plano.isdigit():
        qs = qs.filter(plano_id=int(f_plano))
    if f_solic:
        qs = qs.filter(creado_por__nombre__icontains=f_solic)
    if f_tipo:
        qs = qs.filter(tipo_movimiento=f_tipo)
    if f_desde or f_hasta:
        from datetime import date as _date
        try:
            d0 = _date.fromisoformat(f_desde) if f_desde else _date.min
            d1 = _date.fromisoformat(f_hasta) if f_hasta else _date.max
            ini, fin = _rango_dias(d0, d1)
            qs = qs.filter(fecha__gte=ini, fecha__lte=fin)
        except ValueError:
            pass

    vales = list(qs[:500])
    vig_map = {}
    asigs = AsignacionVale.objects.filter(vale__in=[v.pk for v in vales], vigente=True
                                          ).select_related("asignado_a")
    for a in asigs:
        vig_map[a.vale_id] = a
    if f_desp.isdigit():
        vales = [v for v in vales if v.pk in vig_map and vig_map[v.pk].asignado_a_id == int(f_desp)]

    # Vista despachador: mis asignados vs todos (lectura)
    if not encargado:
        if tab != "todos":
            vales = [v for v in vales if v.pk in vig_map and vig_map[v.pk].asignado_a_id == perfil.pk]
        operables = {v.pk for v in vales if v.pk in vig_map and vig_map[v.pk].asignado_a_id == perfil.pk
                     and v.estado not in ESTADOS_FINALES}
    else:
        operables = {v.pk for v in vales if v.estado not in ESTADOS_FINALES}

    for v in vales:
        v.vigente = vig_map.get(v.pk)
        v.color_semaforo, v.antiguedad_h = _semaforo(v, cfg, v.vigente)

    # Contadores (ámbito del rol). Vigencias en 1 query (no N llamadas).
    ambito = vales if not encargado and tab != "todos" else list(
        Vale.objects.exclude(estado="BORRADOR"))
    _ambito_ids = [v.pk for v in ambito]
    _con_vigencia = set(AsignacionVale.objects.filter(
        vale_id__in=_ambito_ids, vigente=True
    ).values_list("vale_id", flat=True)) if _ambito_ids else set()
    c = {"por_asignar": 0, "asignados": 0, "parciales": 0, "por_cerrar": 0,
         "cerrados": 0, "faltante": 0, "prestamos": 0, "activos": 0, "total": 0}
    for v in ambito:
        c["total"] += 1
        if v.estado in ("EMITIDO", "ASIGNADO", "PARCIAL", "POR_CERRAR"):
            c["activos"] += 1
        if v.estado == "EMITIDO" and v.pk not in _con_vigencia:
            c["por_asignar"] += 1
        elif v.estado == "ASIGNADO":
            c["asignados"] += 1
        elif v.estado == "PARCIAL":
            c["parciales"] += 1
        elif v.estado == "POR_CERRAR":
            c["por_cerrar"] += 1
        elif v.estado == "CERRADO":
            c["cerrados"] += 1
        elif v.estado == "CERRADO_CON_FALTANTE":
            c["faltante"] += 1
        elif v.estado == "PRESTAMO_ABIERTO":
            c["prestamos"] += 1
    c["cerrados_hoy"] = FirmaSnapshot.objects.filter(
        tipo="DESPACHADO", fecha__date=timezone.localdate()).count()

    # Querystrings preservados para tabs y paginación
    qd = request.GET.copy()
    qd.pop("page", None)
    qs_page = qd.urlencode()
    qd.pop("tab", None)
    qd.pop("tab_estado", None)
    qs_base = qd.urlencode()

    paginator = Paginator(vales, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    for v in page_obj:
        if not hasattr(v, "vigente"):
            v.vigente = vig_map.get(v.pk)
        if not hasattr(v, "color_semaforo"):
            v.color_semaforo, v.antiguedad_h = _semaforo(v, cfg, v.vigente)

    tabs_estado = [
        ("activos", "Activos", c["activos"]),
        ("por_asignar", "Por asignar", c["por_asignar"]),
        ("asignados", "Asignados", c["asignados"]),
        ("parciales", "Parciales", c["parciales"]),
        ("por_cerrar", "Por cerrar", c["por_cerrar"]),
        ("cerrados", "Cerrados", c["cerrados"]),
        ("faltante", "C. faltante", c["faltante"]),
        ("prestamos", "Préstamos", c["prestamos"]),
    ]
    hoy = str(timezone.localdate())
    return render(request, "almacen/bandeja/bandeja.html", {
        "page_obj": page_obj, "contadores": c, "encargado": encargado, "tab": tab,
        "tab_estado": tab_estado, "tabs_estado": tabs_estado,
        "qs_base": qs_base, "qs_page": qs_page,
        "operables": operables, "cfg": cfg,
        "despachadores": Perfil.objects.filter(rol_almacen="DESPACHADOR", activo=True).order_by("nombre"),
        "empresas": Empresa.objects.filter(activa=True),
        "areas": Area.objects.filter(activa=True),
        "planos": Plano.objects.filter(activa=True),
        "tipos": Vale.TIPOS_MOVIMIENTO,
        "hoy": hoy,
        "f": {"q": q, "empresa": f_empresa, "area": f_area, "plano": f_plano,
              "solicitante": f_solic, "despachador": f_desp, "tipo": f_tipo, "desde": f_desde, "hasta": f_hasta},
    })

@login_perfil_requerido
@nivel_requerido(3)
def exportar_entregas_excel(request):
    """Excel de materiales entregados en un rango de fechas (a elección).
    Encargado: todo + filtro por despachador. Despachador: solo lo suyo."""
    from datetime import date
    from django.http import HttpResponse
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    encargado = _es_encargado(request)
    hoy = str(timezone.localdate())
    desde = request.GET.get("desde", "") or hoy
    hasta = request.GET.get("hasta", "") or desde
    try:
        desde_d = date.fromisoformat(desde)
        hasta_d = date.fromisoformat(hasta)
    except ValueError:
        messages.error(request, "Fechas inválidas (usa AAAA-MM-DD).")
        return redirect("almacen:bandeja")
    if hasta_d < desde_d:
        messages.error(request, "La fecha final no puede ser anterior a la inicial.")
        return redirect("almacen:bandeja")

    dets = (DetalleEntrega.objects
            .filter(entrega__estado="ACTIVA")
            .select_related("entrega__vale", "entrega__perfil", "entrega__entregado_por",
                            "detalle_vale__material", "detalle_vale__unidad")
            .order_by("entrega__fecha"))
    ini, fin = _rango_dias(desde_d, hasta_d)
    dets = dets.filter(entrega__fecha__gte=ini, entrega__fecha__lte=fin)
    # Filtro por despachador en SQL ANTES del tope (antes filtraba en Python
    # después del [:5000]: traía de más y cortaba mal).
    desp_id = request.GET.get("despachador", "")
    if not encargado:
        dets = dets.filter(entrega__entregado_por=perfil.pk)
    elif desp_id.isdigit():
        dets = dets.filter(entrega__entregado_por_id=int(desp_id))
    dets = list(dets[:5000])

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Entregas"
    ws.append(["Fecha", "Vale N°", "Folio", "Material", "Cantidad", "Unidad",
               "Entregado por", "Registró", "Estado vale", "Observaciones"])
    for d in dets:
        e = d.entrega
        ws.append([
            e.fecha.strftime("%d/%m/%Y %H:%M"),
            e.vale.consecutivo,
            d.detalle_vale.material.folio,
            d.detalle_vale.material.descripcion,
            float(d.cantidad),
            d.detalle_vale.unidad.abreviatura or d.detalle_vale.unidad.nombre,
            e.entregado_por.nombre if e.entregado_por else "",
            e.perfil.nombre,
            e.vale.get_estado_display(),
            d.observaciones,
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            12, min(48, max(len(str(c.value or "")) for c in col) + 2))
    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="entregas_{desde}_a_{hasta}.xlsx"'
    wb.save(resp)
    _registrar_bitacora(perfil, "EXPORTAR_EXCEL",
                        f"Entregas {desde} a {hasta}: {len(dets)} líneas.", request)
    return resp

def _asignar_vales(request, perfil, ids, desp_id, motivo):
    """Asigna varios vales. Devuelve (ok, mensaje). Solo encargado."""
    try:
        destino = Perfil.objects.get(pk=desp_id, activo=True)
    except Perfil.DoesNotExist:
        messages.error(request, "Despachador no válido.")
        return False
    # El encargado puede asignar a despachadores o tomarlo él mismo
    if destino.rol_almacen != "DESPACHADOR" and destino.pk != perfil.pk:
        messages.error(request, "Solo puedes asignar a un despachador activo (o a ti mismo).")
        return False
    n = 0
    with transaction.atomic():
        for vale in Vale.all_objects.select_for_update().filter(pk__in=ids, eliminado=False):
            if vale.estado in ESTADOS_FINALES or vale.estado == "BORRADOR":
                continue
            anterior = vale.asignaciones.filter(vigente=True).first()
            if anterior and anterior.asignado_a_id == destino.pk:
                continue
            if anterior:
                anterior.vigente = False
                if motivo:
                    anterior.motivo_reasignacion = motivo[:255]
                anterior.save(update_fields=["vigente", "motivo_reasignacion"])
            AsignacionVale.objects.create(vale=vale, asignado_a=destino, asignado_por=perfil,
                                          motivo_reasignacion=motivo[:255] if anterior else "")
            if vale.estado == "EMITIDO":
                vale.estado = "ASIGNADO"
                vale.save(update_fields=["estado"])
            _registrar_bitacora(perfil, "REASIGNADO" if anterior else "ASIGNADO",
                                f"Vale {vale.consecutivo} → {destino.nombre}." +
                                (f" Motivo: {motivo}" if motivo and anterior else ""), request)
            n += 1
    messages.success(request, f"{n} vale(s) asignado(s) a {destino.nombre}.")
    return True

@login_perfil_requerido
@nivel_requerido(3)
@require_POST
def vale_asignar(request, pk):
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_encargado(request):
        messages.error(request, "Solo el encargado puede asignar vales.")
        return redirect("almacen:bandeja")
    _asignar_vales(request, perfil, [pk], request.POST.get("despachador_id", ""),
                   request.POST.get("motivo", "").strip())
    return redirect("almacen:panel_detalle", pk=pk)

@login_perfil_requerido
@nivel_requerido(3)
def almacen_detalle(request, pk):
    """Detalle operativo del vale para almacén + línea de tiempo."""
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    vale = get_object_or_404(Vale, pk=pk)
    if vale.estado == "BORRADOR":
        messages.error(request, "Aún es borrador del solicitante.")
        return redirect("almacen:bandeja")
    vigente = _asignacion_vigente(vale)
    operable = _puede_operar(request, vale)
    detalles = list(vale.detalles.select_related("material", "unidad"))
    for d in detalles:
        d.pendiente = d.cantidad_solicitada - d.cantidad_entregada
    entregas = list(vale.entregas.select_related("perfil").prefetch_related("detalles__detalle_vale__material"))
    asignaciones = list(vale.asignaciones.select_related("asignado_a", "asignado_por").order_by("-fecha"))
    firmas = list(vale.firmas.all())
    solicitudes = list(vale.solicitudes_anulacion.select_related("solicitante").order_by("-fecha"))

    # Línea de tiempo
    tl = [{"fecha": vale.fecha, "evento": "Vale emitido", "detalle": f"N° {vale.consecutivo or '—'}"}]
    for a in asignaciones:
        tl.append({"fecha": a.fecha, "evento": "Reasignado" if a.motivo_reasignacion else "Asignado",
                   "detalle": f"{a.asignado_por.nombre} → {a.asignado_a.nombre}" +
                              (f" ({a.motivo_reasignacion})" if a.motivo_reasignacion else "")})
    for e in entregas:
        tl.append({"fecha": e.fecha, "evento": "Entrega anulada" if e.estado == "ANULADA" else "Entrega registrada",
                   "detalle": f"{e.perfil.nombre} ({e.detalles.count()} líneas)"})
    for f in firmas:
        tl.append({"fecha": f.fecha, "evento": f"Firma {f.get_tipo_display()}", "detalle": f.nombre})
    for s in solicitudes:
        tl.append({"fecha": s.fecha, "evento": "Anulación solicitada", "detalle": s.motivo[:100]})
    tl.sort(key=lambda x: x["fecha"], reverse=True)

    return render(request, "almacen/atencion/detalle.html", {
        "vale": vale, "vigente": vigente, "operable": operable,
        "encargado": _es_encargado(request), "detalles": detalles,
        "entregas": entregas, "asignaciones": asignaciones,
        "firmas": firmas, "solicitudes": solicitudes, "timeline": tl,
        "firmas_dos": [f for f in firmas if f.tipo in ("RETIRADO", "DESPACHADO")],
        "despachadores": Perfil.objects.filter(rol_almacen="DESPACHADOR", activo=True).order_by("nombre"),
        "encargados": Perfil.objects.filter(rol_almacen="ENCARGADO", activo=True).order_by("nombre"),
    })

@login_perfil_requerido
@nivel_requerido(3)
def vale_despachar(request, pk):
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    vale = get_object_or_404(Vale, pk=pk)
    if not _puede_operar(request, vale) or vale.estado not in ESTADOS_OPERABLES:
        if _asignacion_vigente(vale) is None and vale.estado in ESTADOS_OPERABLES:
            messages.warning(request, "Primero asigna el vale a un despachador.")
        else:
            messages.error(request, "No puedes despachar este vale.")
        return redirect("almacen:panel_detalle", pk=pk)
    detalles = list(vale.detalles.select_related("material", "unidad"))
    for d in detalles:
        d.pendiente = d.cantidad_solicitada - d.cantidad_entregada

    if request.method == "POST":
        ok, msg = _verificar_pin_operador(perfil, request.POST.get("pin", "").strip(), request, "despacho")
        if not ok:
            messages.error(request, msg)
            return redirect("almacen:vale_despachar", pk=pk)
        # Líneas capturadas
        lineas, errores, sobre = [], [], False
        for d in detalles:
            raw = (request.POST.get(f"cant_{d.pk}", "") or "").strip()
            if not raw:
                continue
            try:
                qty = Decimal(raw.replace(",", "."))
            except InvalidOperation:
                errores.append(f"{d.material.descripcion}: cantidad inválida.")
                continue
            if qty <= 0:
                errores.append(f"{d.material.descripcion}: debe ser mayor a 0.")
                continue
            if qty > d.pendiente:
                sobre = True
            lineas.append((d, qty))
        if not lineas:
            errores.append("Captura al menos una cantidad a entregar.")
        # Sobre-entrega: motivo + PIN de un encargado autorizador
        autorizador = None
        if sobre:
            motivo = request.POST.get("sobre_motivo", "").strip()
            if len(motivo) < 10:
                errores.append("Sobre-entrega: el motivo debe tener al menos 10 caracteres.")
            enc_id = request.POST.get("sobre_encargado", "")
            try:
                autorizador = Perfil.objects.get(pk=int(enc_id), rol_almacen="ENCARGADO", activo=True)
            except (Perfil.DoesNotExist, ValueError, TypeError):
                errores.append("Sobre-entrega: selecciona el encargado que autoriza.")
                autorizador = None
            if autorizador:
                ok2, msg2 = _verificar_pin_operador(autorizador, request.POST.get("sobre_pin", "").strip(),
                                                    request, "autoriza sobre-entrega")
                if not ok2:
                    errores.append(f"Autorización denegada: {msg2}")
        if errores:
            for e in errores:
                messages.error(request, e)
            return redirect("almacen:vale_despachar", pk=pk)

        obs = request.POST.get("observaciones", "").strip()[:255]
        with transaction.atomic():
            vlock = Vale.all_objects.select_for_update().get(pk=vale.pk)
            vigente = vlock.asignaciones.filter(vigente=True).select_related("asignado_a").first()
            entrega = Entrega.objects.create(
                vale=vlock, perfil=perfil,
                entregado_por=vigente.asignado_a if vigente else perfil,
            )
            for d, qty in lineas:
                DetalleEntrega.objects.create(entrega=entrega, detalle_vale=d, cantidad=qty,
                                              observaciones=obs)
                d.refresh_from_db()
            _snapshot_firma(vlock, "ENTREGA", perfil)
            vlock.estado = _recalcular_estado(vlock)
            vlock.save(update_fields=["estado"])
        _registrar_bitacora(perfil, "ENTREGA",
                            f"Vale {vale.consecutivo}: {len(lineas)} líneas. "
                            f"Entrega física: {entrega.entregado_por.nombre}.", request)
        if sobre:
            _registrar_bitacora(autorizador, "SOBRE_ENTREGA_AUTORIZADA",
                                f"Vale {vale.consecutivo}. Motivo: {motivo}. "
                                f"Registró: {perfil.nombre}. AVISO A GERENCIA.", request)
            messages.warning(request, "Sobre-entrega registrada y notificada a Gerencia.")
        else:
            messages.success(request, "Entrega registrada.")
        return redirect("almacen:panel_detalle", pk=pk)

    return render(request, "almacen/atencion/despachar.html", {
        "vale": vale, "detalles": detalles, "vigente": _asignacion_vigente(vale),
        "encargados": Perfil.objects.filter(rol_almacen="ENCARGADO", activo=True).order_by("nombre"),
    })

@login_perfil_requerido
@nivel_requerido(3)
@require_POST
def vale_cerrar(request, pk):
    """Cierre con PIN nuevo (ventana propia) + snapshot DESPACHADO POR.
    Exclusivo del encargado: el despachador entrega, el encargado cierra."""
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    vale = get_object_or_404(Vale, pk=pk)
    if not _puede_cerrar(request) or vale.estado != "POR_CERRAR":
        messages.error(request, "Solo el encargado puede cerrar vales.")
        return redirect("almacen:panel_detalle", pk=pk)
    ok, msg = _verificar_pin_operador(perfil, request.POST.get("pin", "").strip(), request, "cierre")
    if not ok:
        messages.error(request, msg)
        return redirect("almacen:panel_detalle", pk=pk)
    if not getattr(perfil, "firma", None):
        messages.error(request, "Tu perfil no tiene firma cargada. Pide a TI que la registre.")
        return redirect("almacen:panel_detalle", pk=pk)
    with transaction.atomic():
        vlock = Vale.all_objects.select_for_update().get(pk=pk)
        if vlock.estado != "POR_CERRAR":
            messages.error(request, "El vale cambió de estado. Recarga.")
            return redirect("almacen:panel_detalle", pk=pk)
        _snapshot_firma(vlock, "DESPACHADO", perfil)
        vlock.estado = "PRESTAMO_ABIERTO" if vlock.tipo_movimiento == "Préstamo" else "CERRADO"
        vlock.save(update_fields=["estado"])
    _registrar_bitacora(perfil, "VALE_CERRADO", f"Vale {vale.consecutivo} cerrado por {perfil.nombre}.", request)
    messages.success(request, f"Vale {vale.consecutivo} cerrado.")
    return redirect("almacen:panel_detalle", pk=pk)

@login_perfil_requerido
@nivel_requerido(3)
@require_POST
def vale_cerrar_faltante(request, pk):
    """Solo encargado: cierra con faltante (motivo + PIN + bitácora)."""
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_encargado(request):
        messages.error(request, "Solo el encargado puede cerrar con faltante.")
        return redirect("almacen:panel_detalle", pk=pk)
    vale = get_object_or_404(Vale, pk=pk)
    if vale.estado in ESTADOS_FINALES or vale.estado in ("BORRADOR", "EMITIDO"):
        messages.error(request, "Sin entregas registradas no se puede cerrar con faltante.")
        return redirect("almacen:panel_detalle", pk=pk)
    motivo = request.POST.get("motivo", "").strip()
    if len(motivo) < 10:
        messages.error(request, "El motivo debe tener al menos 10 caracteres.")
        return redirect("almacen:panel_detalle", pk=pk)
    ok, msg = _verificar_pin_operador(perfil, request.POST.get("pin", "").strip(), request, "cierre con faltante")
    if not ok:
        messages.error(request, msg)
        return redirect("almacen:panel_detalle", pk=pk)
    if not getattr(perfil, "firma", None):
        messages.error(request, "Tu perfil no tiene firma cargada. Pide a TI que la registre.")
        return redirect("almacen:panel_detalle", pk=pk)
    with transaction.atomic():
        vlock = Vale.all_objects.select_for_update().get(pk=pk)
        _snapshot_firma(vlock, "DESPACHADO", perfil)
        vlock.estado = "CERRADO_CON_FALTANTE"
        vlock.motivo_cierre = motivo
        vlock.save(update_fields=["estado", "motivo_cierre"])
    _registrar_bitacora(perfil, "CIERRE_CON_FALTANTE",
                        f"Vale {vale.consecutivo}. Motivo: {motivo}. AVISO A GERENCIA.", request)
    messages.warning(request, f"Vale {vale.consecutivo} cerrado con faltante. Notificado a Gerencia.")
    return redirect("almacen:panel_detalle", pk=pk)

@login_perfil_requerido
@nivel_requerido(3)
@require_POST
def entrega_anular(request, pk, entrega_id):
    """Solo encargado: anula una entrega (descuenta acumulados)."""
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    if not _es_encargado(request):
        messages.error(request, "Solo el encargado puede anular entregas.")
        return redirect("almacen:panel_detalle", pk=pk)
    vale = get_object_or_404(Vale, pk=pk)
    entrega = get_object_or_404(Entrega, pk=entrega_id, vale=vale, estado="ACTIVA")
    motivo = request.POST.get("motivo", "").strip()
    if len(motivo) < 10:
        messages.error(request, "El motivo debe tener al menos 10 caracteres.")
        return redirect("almacen:panel_detalle", pk=pk)
    ok, msg = _verificar_pin_operador(perfil, request.POST.get("pin", "").strip(), request, "anula entrega")
    if not ok:
        messages.error(request, msg)
        return redirect("almacen:panel_detalle", pk=pk)
    with transaction.atomic():
        vlock = Vale.all_objects.select_for_update().get(pk=pk)
        for de in entrega.detalles.select_related("detalle_vale"):
            dv = de.detalle_vale
            dv.cantidad_entregada = max(Decimal("0"), dv.cantidad_entregada - de.cantidad)
            dv.actualizar_estado()
        entrega.estado = "ANULADA"
        entrega.motivo_anulacion = motivo
        entrega.save(update_fields=["estado", "motivo_anulacion"])
        vlock.estado = _recalcular_estado(vlock)
        vlock.save(update_fields=["estado"])
    _registrar_bitacora(perfil, "ENTREGA_ANULADA",
                        f"Vale {vale.consecutivo}, entrega {entrega.pk}. Motivo: {motivo}. AVISO A GERENCIA.",
                        request)
    messages.warning(request, "Entrega anulada y cantidades descontadas. Notificado a Gerencia.")
    return redirect("almacen:panel_detalle", pk=pk)

@login_perfil_requerido
def vale_imprimir(request, pk):
    """Hoja imprimible con firmas. Solo cuando el vale está cerrado por completo."""
    from django.core.exceptions import PermissionDenied
    perfil = _perfil_o_selector(request)
    if perfil is None:
        return redirect("cuentas:seleccionar_perfil")
    vale = get_object_or_404(Vale, pk=pk)
    nivel = _nivel(request)
    if nivel < 3 and vale.creado_por_id != perfil.pk:
        raise PermissionDenied
    if nivel == 1 and not _es_solicitante(request):
        raise PermissionDenied
    if vale.estado not in ("CERRADO", "CERRADO_CON_FALTANTE"):
        messages.error(request, "Las firmas solo se pueden ver e imprimir cuando el vale está cerrado por completo.")
        if nivel == 1:
            return redirect("almacen:vale_detalle", pk=pk)
        return redirect("almacen:panel_detalle", pk=pk)
    detalles = list(vale.detalles.select_related("material", "unidad"))
    for d in detalles:
        d.pendiente = d.cantidad_solicitada - d.cantidad_entregada
    return render(request, "almacen/imprimir.html", {
        "vale": vale, "detalles": detalles,
        "entregas": list(vale.entregas.select_related("perfil").prefetch_related("detalles__detalle_vale__material")),
        "firmas": list(vale.firmas.all()),
        "cfg": Configuracion.get_solo(),
        "hoy": timezone.localdate(),
    })

# ── Gerencia (Nivel 4) ──────────────────────────────────────────────────────

@login_perfil_requerido
@nivel_requerido(4)
def dashboard_gerencia(request):
    return render(request, "almacen/gerencia/dashboard.html", {})

@login_perfil_requerido
@nivel_requerido(4)
def reporte_excepciones(request):
    return render(request, "almacen/gerencia/excepciones.html", {})
