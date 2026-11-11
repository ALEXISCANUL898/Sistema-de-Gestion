"""Constantes y utilidades compartidas por las vistas de iahelp."""

from datetime import datetime, timedelta
import json
import logging
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

from ..models import EcontrolTicketMessage, TicketMessage
from ..servicios.correo import EmailService, EnkontrolEmailService
from ..servicios.ia_tickets import TicketAIService

logger = logging.getLogger(__name__)


ADMIN_USERNAME = "admin"


HORAS_PROPUESTA_VIGENTE = 24


ESTADOS_ACTIVOS = ("Abierto", "En Progreso")


TICKETS_POR_PAGINA = 50


def _es_admin_real(user):
    """El usuario `admin` local tiene acceso total aunque no tenga permiso de sistema."""
    return bool(user.is_superuser and user.username == ADMIN_USERNAME)


def _nivel_de_permiso(permiso):
    """Convierte a entero el `nivel_acceso` de un permiso del API Central."""
    try:
        return int((permiso or {}).get("nivel_acceso", 0))
    except (TypeError, ValueError):
        return 0


def _nivel_acceso(request, sistema):
    """Nivel de acceso del permiso de `sistema` guardado en la sesión."""
    return _nivel_de_permiso(request.session.get(f"permiso_{sistema}"))


def _destino_login(sistema, nivel):
    """Nombre de URL al que se redirige tras autenticarse en `sistema`."""
    if sistema == "enkontrol":
        return "econtrol_soporte_dashboard" if nivel >= 4 else "econtrol_dashboard"
    if sistema == "reservaciones":
        return "reserva_list"
    if sistema == "intranet":
        return "intranet_mural"
    if sistema == "PRESTAMOS":
        return "prestamo_admin_panel" if nivel >= 4 else "prestamo_solicitud"
    if sistema == "Almacen":
        return "cuentas:seleccionar_perfil"
    if sistema == "Catalogos":
        return "catalogos:empresas"
    return "support_dashboard" if nivel >= 4 else "listikets"


def _exigir_permiso_enkontrol(request, mensaje_extra=""):
    """Valida el permiso de Enkontrol en sesión.

    Devuelve la respuesta de redirección (cerrando la sesión) cuando el acceso
    no está autorizado, o None si el usuario puede continuar.
    """
    permiso = request.session.get("permiso_enkontrol")
    es_admin = _es_admin_real(request.user)

    if not permiso and not es_admin:
        mensaje = "Acceso no autorizado para Enkontrol."
    elif not es_admin and _nivel_de_permiso(permiso) <= 0:
        mensaje = "No tiene permisos para ingresar al sistema Enkontrol."
    else:
        return None

    logout(request)
    messages.error(request, mensaje + mensaje_extra)
    return redirect("econtrol_login")


def _leidos(request, staff=False, sufijo=""):
    """Mapa de tickets leídos guardado en la sesión (staff o usuario)."""
    clave = ("read_tickets_staff" if staff else "read_tickets_user") + sufijo
    return request.session.get(clave, {})


def _marcar_leido(request, ticket_id, staff=False, sufijo=""):
    """Registra en la sesión que el ticket se acaba de abrir."""
    clave = ("read_tickets_staff" if staff else "read_tickets_user") + sufijo
    leidos = request.session.get(clave, {})
    leidos[str(ticket_id)] = timezone.now().isoformat()
    request.session[clave] = leidos
    request.session.modified = True


def _con_ultimo_mensaje(queryset, mensajes_model):
    """Precarga el último mensaje de cada ticket (2 queries, no N+1)."""
    return queryset.prefetch_related(
        Prefetch(
            "messages",
            queryset=mensajes_model.objects.order_by("-created_at"),
            to_attr="msgs_ordenados",
        )
    )


def _tiene_no_leidos(ticket, leidos):
    """True si el último mensaje es posterior a la última lectura del ticket."""
    mensajes = getattr(ticket, "msgs_ordenados", None)
    if not mensajes:
        return False

    marca = leidos.get(str(ticket.id))
    if not marca:
        return True
    try:
        leido = datetime.fromisoformat(marca)
        if timezone.is_naive(leido):
            leido = timezone.make_aware(leido, timezone.get_current_timezone())
        return mensajes[0].created_at > leido
    except (TypeError, ValueError):
        return True


def _filas_tickets(queryset, leidos, incluir_categoria=False):
    """Filas de ticket + bandera de no leído para las plantillas."""
    filas = []
    for t in queryset:
        fila = {
            "id": t.id,
            "title": t.title,
            "nivel": t.nivel,
            "priority": t.priority,
            "status": t.status,
            "usuario": t.usuario,
            "created_at": t.created_at,
            "unread": _tiene_no_leidos(t, leidos),
        }
        if incluir_categoria:
            fila["category"] = t.category or "Sin clasificar"
        filas.append(fila)
    return filas


def _pagina_tickets(queryset, request, por_pagina=10):
    """Página actual del listado de tickets (primera o última si el parámetro no sirve)."""
    paginator = Paginator(queryset, por_pagina)
    try:
        return paginator.page(request.GET.get("page"))
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def _contexto_tickets(queryset, encabezado):
    """Resumen en texto del listado de tickets que se inyecta en el prompt."""
    lineas = [encabezado]
    lineas.extend(
        f"- #{t.id}: {t.title} | Usuario: {t.usuario} | Nivel: {t.nivel} | "
        f"Prioridad: {t.priority} | Estado: {t.status} | "
        f"Creado: {t.created_at.strftime('%Y-%m-%d')}"
        for t in queryset
    )
    return "\n".join(lineas)


def _responder_chat_ia(request, construir_prompt, etiqueta=""):
    """Resuelve una consulta del chat IA con el prompt de sistema indicado."""
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    user_message = (data.get("message") or "").strip()
    if not user_message:
        return JsonResponse({"error": "Mensaje requerido"}, status=400)

    try:
        respuesta = TicketAIService().client.chat(construir_prompt(), user_message)
        return JsonResponse({"success": True, "response": respuesta})
    except Exception as e:
        logger.error(f"Error en chat IA{etiqueta}: {e}")
        return JsonResponse({"error": str(e)}, status=500)


def _fechas_de_reporte(request):
    """Fechas obligatorias del reporte (`YYYY-MM-DD`). None si faltan."""
    fecha_inicio = request.GET.get("fecha_inicio")
    fecha_fin = request.GET.get("fecha_fin")
    if not fecha_inicio or not fecha_fin:
        return None

    inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    fin = datetime.strptime(fecha_fin, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    if settings.USE_TZ:
        inicio = timezone.make_aware(inicio)
        fin = timezone.make_aware(fin)
    return fecha_inicio, fecha_fin, inicio, fin


def _rango_fechas_reporte(request, dias=30):
    """Fechas del reporte con valores por defecto (últimos `dias`)."""
    fecha_inicio = request.GET.get("fecha_inicio") or (
        timezone.now() - timedelta(days=dias)
    ).strftime("%Y-%m-%d")
    fecha_fin = request.GET.get("fecha_fin") or timezone.now().strftime("%Y-%m-%d")
    try:
        inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
        fin = datetime.strptime(fecha_fin, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        if settings.USE_TZ:
            inicio = timezone.make_aware(inicio)
            fin = timezone.make_aware(fin)
    except ValueError:
        inicio = timezone.now() - timedelta(days=dias)
        fin = timezone.now()
    return fecha_inicio, fecha_fin, inicio, fin


def _horas_promedio_resolucion(tickets):
    """Horas promedio entre creación y última actualización de los cerrados."""
    tiempos = [
        (fila["updated_at"] - fila["created_at"]).total_seconds() / 3600
        for fila in tickets.filter(status="Cerrado").values("created_at", "updated_at")
        if fila["updated_at"] and fila["created_at"]
    ]
    return sum(tiempos) / len(tiempos) if tiempos else None


def _clasificar_mensaje(msg, ticket):
    """Etiqueta visible y tipo de mensaje para los endpoints de conversación."""
    texto = msg.message or ""
    if texto.startswith("[RESOLUTION_PROPOSAL]"):
        return "Propuesta — Equipo TI", "proposal"
    if texto.startswith("[AUTO_CLOSED]"):
        return "Cierre automático", "auto_closed"
    if texto.startswith(("[USER_CONFIRMED]", "[TICKET_CERRADO]", "✅")):
        return "Sistema — Cierre", "confirmed"
    if msg.sender == "ai":
        return "Asistente", "ai"
    if msg.sender == "agent":
        return "Agente de Soporte", "agent"
    return ticket.usuario or "Usuario", "user"


def _buscar_permiso_sistema(permisos, sistema, url_actual):
    """Ubica en los permisos del API Central el del sistema solicitado.

    El API identifica los sistemas por código, por nombre o por URL; se
    aceptan las tres vías para no depender de una sola representación.
    """
    objetivo = (sistema or "").lower()
    for permiso in permisos:
        codigo = str(permiso.get("sistema_codigo", "")).strip().upper()
        codigo_limpio = codigo.lstrip("0")
        nombre = str(permiso.get("sistema_nombre", "")).strip().lower()
        url = permiso.get("sistema_url", "").strip().lower().rstrip("/")

        if objetivo == "iahelp" and (
            codigo in ("IAHELP", "IA_HELP", "TICKETS", "TIKETS", "IA", "001", "0001", "1")
            or codigo_limpio == "1"
            or "TICKET" in codigo
            or "TIKET" in codigo
        ):
            return permiso
        if objetivo == "enkontrol" and (
            codigo in ("ENKONTROL", "EK", "ERP", "002", "0002", "2")
            or codigo_limpio == "2"
            or "ENKONTROL" in codigo
        ):
            return permiso
        if objetivo == "reservaciones" and (
            codigo in ("RESERVACIONES", "RESERVAS", "003", "0003", "3")
            or codigo_limpio == "3"
            or "RESERVA" in codigo
        ):
            return permiso
        if objetivo == "intranet" and (
            codigo in ("INTRANET", "MURAL", "004", "0004", "005", "0005", "4", "5")
            or codigo_limpio in ("4", "5")
            or "INTRANET" in codigo
        ):
            return permiso
        if objetivo == "prestamos" and (
            codigo in ("PRESTAMOS", "PRESTAMO", "005", "0005", "006", "0006", "5", "6")
            or codigo_limpio in ("5", "6")
            or "PRESTAMO" in codigo
        ):
            return permiso
        if objetivo in ("almacen", "almacén") and (
            codigo in ("004", "0004", "4", "ALMACEN")
            or "almacen" in nombre
            or "almacén" in nombre
        ):
            return permiso
        if objetivo in ("catalogos", "catálogos", "catalogo") and (
            codigo in ("005", "0005", "5", "CATALOGOS", "CATALOGO")
            or "catalogo" in nombre
            or "catálogo" in nombre
        ):
            return permiso
        if objetivo in ("auditoria", "auditoría") and (
            codigo in ("006", "0006", "6", "AUDITORIA")
            or "auditoria" in nombre
            or "auditoría" in nombre
        ):
            return permiso

        # Coincidencia por URL o por nombre del sistema
        if url and url == url_actual:
            return permiso
        if objetivo in nombre:
            return permiso
        if objetivo == "iahelp" and any(
            k in nombre
            for k in ("ticket", "tikets", "iahelp", "ia_help", "ia help", "help", "soporte")
        ):
            return permiso
        if objetivo == "enkontrol" and "enkontrol" in nombre:
            return permiso
        if objetivo == "reservaciones" and any(k in nombre for k in ("reserva", "reservacion")):
            return permiso
    return None


def _latest_resolution_proposal(ticket):
    return (
        TicketMessage.objects.filter(
            ticket=ticket, sender="agent", message__startswith="[RESOLUTION_PROPOSAL]"
        )
        .order_by("-created_at")
        .first()
    )


def _message_is_user_confirmation(text: str) -> bool:
    """Detecta si el mensaje del usuario es una confirmación de que el problema está resuelto."""
    if not text:
        return False

    # Limpiar el texto: minúsculas y sin puntuación final
    text_clean = re.sub(r"[.!?¡¿,;:]*$", "", text.lower()).strip()

    logger.debug("Verificando confirmación en mensaje: '%s'", text_clean)

    # Palabras que indican confirmación positiva del usuario
    confirmation_keywords = [
        "confirmo",
        "confirmado",
        "resuelto",
        "resolvido",
        "solucionado",
        "está solucionado",
        "esta solucionado",
        "ya está funcionando",
        "ya esta funcionando",
        "ya funciona",
        "si funciona",
        "sí funciona",
        "si funciono",
        "sí funcionó",
        "si funcionó",
        "funciono",  # sin sí
        "funciona",  # cuando es standalone
        "funciona bien",
        "funciona correctamente",
        "todo bien",
        "todo perfecto",
        "ya pude",
        "ya puedo",
        "ya inicie",
        "ya inicié",
        "ya accedí",
        "ya accedi",
        "perfecto",
        "excelente",
        "muchas gracias",
        "gracias",
        "listo",
        "ok",
        "okey",
        "sí",
        "si",
        "cerrar",
        "puede cerrar",
        "todo funciona",
        "quedó resuelto",
        "quedo resuelto",
        "quedo listo",
        "quedó listo",
        "ya quedo",
        "ya está listo",
        "ya esta listo",
    ]

    # Palabras que indican que NO está resuelto (negaciones)
    negation_keywords = [
        "no funciona",
        "no pude",
        "no puedo",
        "no inicia",
        "no accedo",
        "sigue sin",
        "aún hay",
        "aun hay",
        "aún no",
        "aun no",
        "todavía no",
        "todavia no",
        "persiste",
        "sigue el problema",
        "no resuelto",
        "no solucionado",
        "aun no funciona",
        "todavia no funciona",
    ]

    has_negation = any(k in text_clean for k in negation_keywords)
    if has_negation:
        logger.debug("Negación detectada en mensaje: '%s'", text_clean)
        return False

    is_confirmed = any(k in text_clean for k in confirmation_keywords)
    logger.debug("Confirmación detectada: %s", is_confirmed)
    return is_confirmed


def _cerrar_por_propuesta_vencida(ticket, mensajes_model, buscar_propuesta, notificar):
    """Cierra el ticket si su propuesta de resolución lleva >= 24 h sin respuesta.

    ``notificar(ticket, ai_summary=...)`` envía el correo de cierre.
    Devuelve True si el ticket se cerró en esta llamada.
    """
    if ticket.status == "Cerrado":
        return False

    propuesta = buscar_propuesta(ticket)
    if not propuesta:
        return False
    if timezone.now() - propuesta.created_at < timedelta(hours=HORAS_PROPUESTA_VIGENTE):
        return False
    if mensajes_model.objects.filter(
        ticket=ticket, sender="user", created_at__gt=propuesta.created_at
    ).exists():
        return False

    ticket.status = "Cerrado"
    ticket.save()

    try:
        resumen = TicketAIService().generate_ticket_summary(ticket)
        texto = (
            "[AUTO_CLOSED] La propuesta de resolución no fue confirmada por el usuario "
            f"en el plazo de {HORAS_PROPUESTA_VIGENTE} horas. "
            "Ticket cerrado automáticamente.\n\n"
            f"RESUMEN DEL TICKET:\n{resumen}"
        )
    except Exception:
        texto = (
            "[AUTO_CLOSED] La propuesta de resolución no fue confirmada por el usuario "
            f"en el plazo de {HORAS_PROPUESTA_VIGENTE} horas. Ticket cerrado automáticamente."
        )

    mensajes_model.objects.create(ticket=ticket, sender="agent", message=texto)

    try:
        notificar(ticket, ai_summary=ticket.ai_summary)
    except Exception as exc:
        logger.error(
            "Error al enviar correo de cierre automático para ticket #%s: %s",
            ticket.id,
            exc,
        )
    return True


def _auto_close_expired_proposal(ticket):
    return _cerrar_por_propuesta_vencida(
        ticket,
        TicketMessage,
        _latest_resolution_proposal,
        EmailService.send_ticket_closed_to_all,
    )


def _econtrol_latest_resolution_proposal(ticket):
    return (
        EcontrolTicketMessage.objects.filter(
            ticket=ticket, sender="agent", message__startswith="[RESOLUTION_PROPOSAL]"
        )
        .order_by("-created_at")
        .first()
    )


def _econtrol_auto_close_expired_proposal(ticket):
    return _cerrar_por_propuesta_vencida(
        ticket,
        EcontrolTicketMessage,
        _econtrol_latest_resolution_proposal,
        EnkontrolEmailService.send_ticket_closed_to_all,
    )
