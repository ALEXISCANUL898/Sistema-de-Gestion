"""Cola de trabajos en MySQL para la IA (etapa 4C, sin broker externo).

- Vistas: encolan el análisis y responden al instante si el worker vive.
- Worker (`manage.py cola_worker --once`, tarea cada 2 min): procesa con SKIP LOCKED.
- Si el worker muere (sin latido 5 min), las vistas usan la vía sincrónica de siempre.
"""
import logging
import time

from django.db import transaction
from django.utils import timezone

from ..models import TrabajoFondo, LatidoWorker, Ticket, TicketMessage
from ..models import EcontrolTicket, EcontrolTicketMessage

logger = logging.getLogger(__name__)

LATIDO_NOMBRE = "cola"
LATIDO_VIVO_MIN = 5

_viva_cache = {"ts": 0.0, "valor": False}


def _ahora():
    return timezone.now()


def latir():
    """Marca heartbeat del worker. Idempotente."""
    LatidoWorker.objects.update_or_create(
        nombre=LATIDO_NOMBRE, defaults={"ultimo": _ahora()})


def cola_viva():
    """True si el worker dio señales en los últimos minutos (caché 30s)."""
    now = time.monotonic()
    if now - _viva_cache["ts"] < 30:
        return _viva_cache["valor"]
    try:
        vivo = LatidoWorker.objects.filter(
            nombre=LATIDO_NOMBRE, ultimo__gte=_ahora() - timezone.timedelta(minutes=LATIDO_VIVO_MIN)
        ).exists()
    except Exception:
        vivo = False
    _viva_cache.update(ts=now, valor=vivo)
    return vivo


def hay_trabajo_pendiente(tipo, ticket_id):
    return TrabajoFondo.objects.filter(
        tipo=tipo, ticket_id=ticket_id, estado__in=("PENDIENTE", "PROCESANDO")).exists()


def encolar(tipo, ticket_id, payload=None):
    return TrabajoFondo.objects.create(
        tipo=tipo, ticket_id=ticket_id,
        programado_para=_ahora(), payload=payload or {})


def encolar_analisis_ticket(ticket_id, nivel_usuario):
    return encolar("ANALIZAR_TICKET", ticket_id, {"nivel_usuario": nivel_usuario})


def encolar_analisis_econtrol(ticket_id, nivel_usuario, categoria_post=""):
    return encolar("ANALIZAR_ECONTROL", ticket_id,
                   {"nivel_usuario": nivel_usuario, "categoria_post": categoria_post or ""})


def aplicar_analisis_ticket(ticket, analysis, nivel_usuario):
    """Misma lógica que el index sincrónico (única fuente). Devuelve ai_nivel."""
    ai_nivel = analysis.get("nivel", 1)
    if ai_nivel == 4:
        if nivel_usuario >= 4:
            pass
        elif nivel_usuario == 3:
            ai_nivel = 3
        else:
            ai_nivel = 3
    ai_nivel = max(1, min(4, ai_nivel))
    Ticket.objects.filter(id=ticket.id).update(
        nivel=ai_nivel,
        category=analysis.get("category", "General"),
        priority=analysis.get("priority", "Media"),
        ai_summary=analysis.get("ai_summary", ""),
        ai_suggested_response=analysis.get("ai_suggested_response", "")
    )
    ticket.refresh_from_db()
    if not TicketMessage.objects.filter(ticket=ticket, sender="ai").exists():
        TicketMessage.objects.create(
            ticket=ticket,
            sender="ai",
            message=ticket.ai_suggested_response,
        )
    return ai_nivel


def aplicar_analisis_econtrol(ticket, analysis, nivel_usuario, categoria_post=""):
    """Misma lógica que econtrol_crear sincrónico (única fuente)."""
    from .datos_enkontrol import classify_category  # noqa
    ai_nivel = analysis.get("nivel", 1)
    if ai_nivel == 4 and nivel_usuario < 4:
        ai_nivel = 3
    ai_nivel = max(1, min(4, ai_nivel))
    final_category = categoria_post
    if not final_category or final_category == "Automática":
        final_category = classify_category(ticket.description)
    EcontrolTicket.objects.filter(id=ticket.id).update(
        nivel=ai_nivel,
        priority=analysis.get("priority", "Media"),
        category=final_category,
        ai_summary=analysis.get("ai_summary", ""),
        ai_suggested_response=analysis.get("ai_suggested_response", "")
    )
    ticket.refresh_from_db()
    ai_message = ticket.ai_suggested_response or ""
    if not ai_message:
        try:
            from .ia_tickets import TicketAIService
            _svc = TicketAIService()
            ai_message = _svc.generate_reply(
                ticket,
                f"Usuario reporta incidencia en {ticket.title}: {ticket.description}",
                is_high_priority=nivel_usuario >= 3,
            )
            logger.info("IA generó respuesta automática para ticket %s", ticket.id)
        except Exception as exc:
            logger.error("Error al generar respuesta automática: %s", exc)
            ai_message = "Gracias por reportar su incidencia. El equipo de Soporte Enkontrol atenderá su solicitud a la brevedad."
    if not EcontrolTicketMessage.objects.filter(ticket=ticket, sender="ai").exists():
        EcontrolTicketMessage.objects.create(
            ticket=ticket,
            sender="ai",
            message=ai_message,
        )
    return ai_nivel


def _procesar_analizar_ticket(job):
    from .ia_tickets import TicketAIService
    from .correo import EmailService
    ticket = Ticket.objects.get(id=job.ticket_id)
    nivel_usuario = int((job.payload or {}).get("nivel_usuario", 1))
    svc = TicketAIService()
    analysis = svc.analyze(
        ticket.description, ticket=ticket, is_high_priority=nivel_usuario >= 3)
    ai_nivel = aplicar_analisis_ticket(ticket, analysis, nivel_usuario)
    try:
        EmailService.send_ticket_created_to_user(ticket)
        EmailService.send_new_ticket_to_support(ticket)
    except Exception as exc:
        logger.warning("Correo fondo ticket %s: %s", ticket.id, exc)
    return f"Nivel {ai_nivel}"


def _procesar_analizar_econtrol(job):
    from .ia_tickets import TicketAIService
    from .correo import EnkontrolEmailService
    ticket = EcontrolTicket.objects.get(id=job.ticket_id)
    nivel_usuario = int((job.payload or {}).get("nivel_usuario", 4))
    categoria_post = (job.payload or {}).get("categoria_post", "")
    svc = TicketAIService()
    analysis = svc.analyze(
        ticket.description, ticket=ticket, is_high_priority=nivel_usuario >= 3)
    ai_nivel = aplicar_analisis_econtrol(ticket, analysis, nivel_usuario, categoria_post)
    try:
        EnkontrolEmailService.send_ticket_created_to_user(ticket)
        EnkontrolEmailService.send_new_ticket_to_support(ticket)
    except Exception as exc:
        logger.warning("Correo fondo enkontrol %s: %s", ticket.id, exc)
    return f"Nivel {ai_nivel}"


PROCESADORES = {
    "ANALIZAR_TICKET": _procesar_analizar_ticket,
    "ANALIZAR_ECONTROL": _procesar_analizar_econtrol,
}


def tomar_lote(limite=5):
    """Reserva hasta `limite` trabajos vencidos con SKIP LOCKED (MySQL 8)."""
    with transaction.atomic():
        ids = list(
            TrabajoFondo.objects.select_for_update(skip_locked=True)
            .filter(estado="PENDIENTE", programado_para__lte=_ahora())
            .order_by("programado_para", "id")
            .values_list("id", flat=True)[:limite]
        )
        if ids:
            TrabajoFondo.objects.filter(pk__in=ids).update(estado="PROCESANDO")
        return list(TrabajoFondo.objects.filter(pk__in=ids))


def procesar_trabajo(job):
    """Ejecuta un trabajo con reintentos y backoff. Devuelve True si OK."""
    fn = PROCESADORES.get(job.tipo)
    if fn is None:
        job.estado = "ERROR"
        job.error = f"Tipo desconocido: {job.tipo}"
        job.save(update_fields=["estado", "error"])
        return False
    try:
        job.resultado = fn(job) or ""
        job.estado = "OK"
        job.error = ""
        job.save(update_fields=["resultado", "estado", "error"])
        return True
    except Exception as exc:
        logger.exception("Trabajo %s #%s falló", job.tipo, job.ticket_id)
        job.intentos += 1
        if job.intentos >= job.max_intentos:
            job.estado = "ERROR"
            job.error = str(exc)[:2000]
            job.save(update_fields=["intentos", "estado", "error"])
        else:
            espera_min = 2 ** job.intentos
            job.estado = "PENDIENTE"
            job.programado_para = _ahora() + timezone.timedelta(minutes=espera_min)
            job.error = str(exc)[:2000]
            job.save(update_fields=["intentos", "estado", "programado_para", "error"])
        return False
