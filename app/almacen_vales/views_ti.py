"""
Vistas TI del módulo almacén_vales (Nivel 6):
  - Eliminación lógica de vales (con PIN + bitácora + notificación)
  - Restauración de vales eliminados
  - Bandeja de solicitudes de anulación
  - Bitácora de auditoría (solo lectura)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone

from app.cuentas.decorators import nivel_requerido
from app.auditoria.models import Bitacora
from .models import Vale, SolicitudAnulacion


def _bitacora(perfil, accion, detalle, request):
    ip = request.META.get("REMOTE_ADDR", "")
    Bitacora.objects.create(perfil=perfil, accion=accion, detalle=detalle, ip=ip)


# ─── Vales eliminados ─────────────────────────────────────────────────────────

@nivel_requerido(6)
def vales_eliminados(request):
    qs = Vale.all_objects.filter(eliminado=True).select_related(
        "creado_por", "empresa", "eliminado_por"
    ).order_by("-fecha")

    # Filtros opcionales
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(consecutivo__icontains=q)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "almacen/ti/vales_eliminados.html", {
        "page_obj": page_obj, "q": q,
    })


@nivel_requerido(6)
def vale_eliminar(request, vale_id):
    """
    Eliminación lógica de un vale (solo TI / Nivel 6).
    Requiere motivo mínimo + PIN del perfil TI.
    La acción se completa en dos pasos:
      1. GET  → muestra formulario con resumen del vale y campo motivo.
      2. POST → valida PIN vía API y ejecuta el soft-delete.
    """
    vale = get_object_or_404(Vale.all_objects, pk=vale_id, eliminado=False)
    if request.method == "POST":
        motivo = request.POST.get("motivo", "").strip()
        pin = request.POST.get("pin", "").strip()

        if len(motivo) < 10:
            messages.error(request, "El motivo debe tener al menos 10 caracteres.")
            return render(request, "almacen/ti/vale_eliminar.html", {"vale": vale})

        perfil = request.perfil_activo
        if perfil.is_locked():
            messages.error(request, "Tu perfil está bloqueado.")
            return redirect("almacen:vales_eliminados")

        if not perfil.check_pin(pin):
            perfil.intentos_fallidos += 1
            if perfil.intentos_fallidos >= 5:
                perfil.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=15)
                _bitacora(perfil, "PERFIL_BLOQUEADO", "Intento fallido al eliminar vale", request)
            perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
            messages.error(request, "PIN incorrecto.")
            return render(request, "almacen/ti/vale_eliminar.html", {"vale": vale})

        # Ejecutar soft-delete
        vale.soft_delete(perfil, motivo)
        _bitacora(
            perfil,
            "VALE_ELIMINADO",
            f"Vale {vale.consecutivo} eliminado. Motivo: {motivo}",
            request,
        )
        # Notificación interna a Gerencia (Nivel 4) — se crea registro en Bitácora
        # (en Fase 6 se añadirá notificación push/email)
        messages.success(
            request,
            f"Vale {vale.consecutivo} eliminado lógicamente. "
            "Se ha registrado en la bitácora y notificado a Gerencia.",
        )
        return redirect("almacen:vales_eliminados")

    return render(request, "almacen/ti/vale_eliminar.html", {"vale": vale})


@nivel_requerido(6)
def vale_restaurar(request, vale_id):
    """Restaura un vale eliminado (requiere PIN + motivo)."""
    vale = get_object_or_404(Vale.all_objects, pk=vale_id, eliminado=True)
    if request.method == "POST":
        motivo = request.POST.get("motivo", "").strip()
        pin = request.POST.get("pin", "").strip()

        if len(motivo) < 10:
            messages.error(request, "El motivo debe tener al menos 10 caracteres.")
            return render(request, "almacen/ti/vale_restaurar.html", {"vale": vale})

        perfil = request.perfil_activo
        if not perfil.check_pin(pin):
            perfil.intentos_fallidos += 1
            perfil.save(update_fields=["intentos_fallidos"])
            messages.error(request, "PIN incorrecto.")
            return render(request, "almacen/ti/vale_restaurar.html", {"vale": vale})

        vale.eliminado = False
        vale.eliminado_por = None
        vale.motivo_eliminacion = ""
        vale.save(update_fields=["eliminado", "eliminado_por", "motivo_eliminacion"])
        _bitacora(
            perfil,
            "VALE_RESTAURADO",
            f"Vale {vale.consecutivo} restaurado. Motivo: {motivo}",
            request,
        )
        messages.success(request, f"Vale {vale.consecutivo} restaurado correctamente.")
        return redirect("almacen:vales_eliminados")

    return render(request, "almacen/ti/vale_restaurar.html", {"vale": vale})


# ─── Solicitudes de anulación ─────────────────────────────────────────────────

@nivel_requerido(6)
def solicitudes_anulacion(request):
    filtro = request.GET.get("filtro", "pendientes")
    qs = SolicitudAnulacion.objects.select_related(
        "vale", "solicitante", "aprobado_por"
    ).order_by("-fecha")

    if filtro == "pendientes":
        qs = qs.filter(aprovada__isnull=True)
    elif filtro == "aprobadas":
        qs = qs.filter(aprovada=True)
    elif filtro == "rechazadas":
        qs = qs.filter(aprovada=False)
    # "todas" → no filter

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "almacen/ti/solicitudes_anulacion.html", {
        "page_obj": page_obj,
        "filtro": filtro,
        "pendientes_count": SolicitudAnulacion.objects.filter(aprovada__isnull=True).count(),
        "filtros": [
            ("pendientes", "Pendientes"),
            ("aprobadas", "Aprobadas"),
            ("rechazadas", "Rechazadas"),
            ("todas", "Todas"),
        ],
    })


@nivel_requerido(6)
def solicitud_resolver(request, solicitud_id):
    """Aprueba o rechaza una solicitud de anulación con PIN."""
    solicitud = get_object_or_404(SolicitudAnulacion, pk=solicitud_id, aprovada__isnull=True)
    if request.method == "POST":
        accion = request.POST.get("accion")   # "aprobar" o "rechazar"
        pin = request.POST.get("pin", "").strip()
        motivo_resolucion = request.POST.get("motivo_resolucion", "").strip()

        if accion not in ("aprobar", "rechazar"):
            messages.error(request, "Acción inválida.")
            return redirect("almacen:solicitudes_anulacion")

        perfil = request.perfil_activo
        if not perfil.check_pin(pin):
            perfil.intentos_fallidos += 1
            perfil.save(update_fields=["intentos_fallidos"])
            messages.error(request, "PIN incorrecto.")
            return render(request, "almacen/ti/solicitud_resolver.html", {
                "solicitud": solicitud,
            })

        solicitud.aprovada = (accion == "aprobar")
        solicitud.aprobado_por = perfil
        solicitud.fecha_aprobacion = timezone.now()
        solicitud.save(update_fields=["aprovada", "aprobado_por", "fecha_aprobacion"])

        if accion == "aprobar":
            # Anular el vale lógicamente
            vale = solicitud.vale
            vale.soft_delete(perfil, f"Anulado por solicitud #{solicitud.pk}: {motivo_resolucion}")
            accion_log = "SOLICITUD_APROBADA"
            msg = f"Solicitud aprobada. Vale {vale.consecutivo} anulado."
        else:
            accion_log = "SOLICITUD_RECHAZADA"
            msg = "Solicitud rechazada."

        _bitacora(perfil, accion_log,
                  f"Solicitud #{solicitud.pk} del vale {solicitud.vale.consecutivo}. "
                  f"Motivo resolución: {motivo_resolucion}",
                  request)
        messages.success(request, msg)
        return redirect("almacen:solicitudes_anulacion")

    return render(request, "almacen/ti/solicitud_resolver.html", {"solicitud": solicitud})


# ─── Bitácora (solo lectura) ──────────────────────────────────────────────────

@nivel_requerido(6)
def bitacora_list(request):
    qs = Bitacora.objects.select_related("perfil").order_by("-fecha")

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(accion__icontains=q)
    fecha_desde = request.GET.get("fecha_desde", "")
    fecha_hasta = request.GET.get("fecha_hasta", "")
    if fecha_desde or fecha_hasta:
        from datetime import date as _date
        from .views import _rango_dias
        try:
            d0 = _date.fromisoformat(fecha_desde) if fecha_desde else _date.min
            d1 = _date.fromisoformat(fecha_hasta) if fecha_hasta else _date.max
            ini, fin = _rango_dias(d0, d1)
            qs = qs.filter(fecha__gte=ini, fecha__lte=fin)
        except ValueError:
            pass

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "almacen/ti/bitacora.html", {
        "page_obj": page_obj,
        "q": q,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
    })
