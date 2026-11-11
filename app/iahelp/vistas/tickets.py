"""Vistas y API de los tickets de IA Help."""

from datetime import datetime
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..infraestructura.decoradores import permission_level_required
from ..models import Ticket, TicketMessage
from ..servicios.correo import EmailService
from ..servicios.ia_tickets import TicketAIService

from .comunes import (
    ESTADOS_ACTIVOS,
    TICKETS_POR_PAGINA,
    _auto_close_expired_proposal,
    _clasificar_mensaje,
    _con_ultimo_mensaje,
    _es_admin_real,
    _filas_tickets,
    _latest_resolution_proposal,
    _leidos,
    _marcar_leido,
    _message_is_user_confirmation,
    _nivel_acceso,
    _pagina_tickets,
)

logger = logging.getLogger(__name__)

# API Endpoints para actualizaciones en tiempo real

@require_http_methods(["GET"])
def api_ticket_messages(request, ticket_id):
    """API endpoint para obtener mensajes de un ticket en JSON."""
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        return JsonResponse({"error": "Ticket no encontrado"}, status=404)

    # Verificar permisos: usuario dueño o personal de soporte (nivel 4+)
    nivel_acceso = _nivel_acceso(request, "iahelp")
    is_support_staff = request.user.is_superuser or nivel_acceso >= 4

    if ticket.user != request.user and not is_support_staff:
        return JsonResponse({"error": "No autorizado"}, status=403)

    messages_data = []
    for msg in ticket.messages.all().order_by("created_at"):
        sender_label = getattr(msg, "sender_label", None)
        if not sender_label:
            sender_label = {
                "ai": "IA",
                "agent": "Soporte",
                "system": "Sistema",
            }.get(msg.sender, ticket.usuario)

        messages_data.append(
            {
                "id": msg.id,
                "sender": msg.sender,
                "sender_label": sender_label,
                "message": msg.message,
                "created_at": msg.created_at.strftime("%d/%m/%Y %H:%M"),
            }
        )

    return JsonResponse(
        {
            "ticket_id": ticket.id,
            "ticket_status": ticket.status,
            "messages": messages_data,
        }
    )


def ticket_detail(request, ticket_id):
    """Detalle de ticket con conversación y respuesta IA. Solo el creador o soporte pueden verlo."""
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        messages.error(request, "Ticket no encontrado.")
        return redirect("listikets")

    # Solo personal de soporte (nivel 4+) o el admin real
    nivel_acceso = _nivel_acceso(request, "iahelp")
    is_support_staff = _es_admin_real(request.user) or nivel_acceso >= 4

    # Validar permisos: solo el creador o personal de soporte autorizado puede ver
    if ticket.user != request.user and not is_support_staff:
        messages.error(request, "No tienes permiso para ver este ticket.")
        return redirect("listikets")

    # Marcar el ticket como leído al abrir el detalle
    if request.method == "GET":
        _marcar_leido(request, ticket_id, staff=request.user.is_superuser)

    # Ejecutar cierre automático si existiera una propuesta vencida
    try:
        _auto_close_expired_proposal(ticket)
    except Exception:
        logger.exception("Error al comprobar cierre automático de propuestas")

    if request.method == "POST":
        message_text = request.POST.get("message", "").strip()

        if message_text:
            # Determinar si el remitente es un técnico/soporte
            is_tech_support = request.user.is_superuser or nivel_acceso >= 3
            # Si es mensaje de soporte, asegurar que el estado sea En Progreso
            if is_tech_support and ticket.status not in ("En Progreso", "Cerrado"):
                ticket.status = "En Progreso"
                ticket.save()
            sender_type = "agent" if is_tech_support else "user"

            # Guardar mensaje del usuario/técnico
            TicketMessage.objects.create(
                ticket=ticket,
                sender=sender_type,
                message=message_text,
            )

            # Si es técnico de soporte, detectar resolución con IA y enviar correo según resultado
            if is_tech_support:
                try:
                    svc = TicketAIService()
                    resolution_analysis = svc.detect_resolution(ticket, message_text)

                    if resolution_analysis.get(
                        "is_resolved"
                    ) and resolution_analysis.get("confidence") in ("alta", "media"):
                        closure_message = svc.generate_closure_message(
                            ticket,
                            resolution_analysis.get(
                                "solution_summary", "Problema resuelto"
                            ),
                        )

                        proposal_text = "[RESOLUTION_PROPOSAL]\n" + closure_message

                        TicketMessage.objects.create(
                            ticket=ticket,
                            sender="agent",
                            message=proposal_text,
                        )

                        # Marcar en progreso si aún está abierto
                        if ticket.status == "Abierto":
                            ticket.status = "En Progreso"
                            ticket.save()

                        messages.info(
                            request,
                            "Propuesta de resolución enviada. Se espera confirmación del usuario (24h).",
                        )

                        # Escenario 5: propuesta de cierre → email al usuario para confirmar
                        try:
                            EmailService.send_resolution_proposal_to_user(ticket)
                        except Exception as e:
                            logger.warning(f"Error enviando email de propuesta: {e}")
                    else:
                        # Escenario 3: soporte responde sin resolución → email al usuario
                        try:
                            EmailService.send_ticket_response(ticket, message_text, request.user.username)
                        except Exception as e:
                            logger.warning(f"No se pudo enviar notificación por correo: {e}")
                except Exception as e:
                    logger.error("Error al detectar resolución (propuesta): %s", str(e))
                    # Fallback: enviar notificación estándar al usuario
                    try:
                        EmailService.send_ticket_response(ticket, message_text, request.user.username)
                    except Exception as email_e:
                        logger.warning(f"Error enviando email fallback: {email_e}")

            else:
                # Usuario regular
                # Si el ticket está cerrado, reabrirlo
                if ticket.status == "Cerrado":
                    ticket.status = "Abierto"
                    ticket.save()

                    # Generar respuesta automática de reapertura
                    try:
                        svc = TicketAIService()
                        reopen_message = svc.generate_reopen_response(
                            ticket, message_text
                        )

                        TicketMessage.objects.create(
                            ticket=ticket,
                            sender="agent",
                            message=f"[TICKET_REABIERTO]\n{reopen_message}",
                        )
                        messages.info(
                             request,
                             "Tu ticket ha sido reabierto. El equipo de soporte revisará tu caso.",
                        )

                        # Escenario 7: ticket reabierto → email a soporte
                        try:
                            EmailService.send_ticket_reopened_to_support(ticket, message_text)
                        except Exception as e:
                            logger.warning(f"Error enviando email de reapertura: {e}")

                        logger.info(f"Ticket {ticket.id} reabierto por el usuario")
                    except Exception as e:
                        logger.error(f"Error al generar respuesta de reapertura: {e}")
                        TicketMessage.objects.create(
                            ticket=ticket,
                            sender="agent",
                            message="[TICKET_REABIERTO] Hemos recibido tu mensaje. El equipo de soporte revisará tu caso a la brevedad.",
                        )
                        messages.info(request, "Tu ticket ha sido reabierto.")

                # Comprobar si confirma una propuesta previa
                else:
                    try:
                        latest_proposal = _latest_resolution_proposal(ticket)
                        logger.info(
                            f"Usuario envió mensaje: '{message_text}' - Propuesta encontrada: {latest_proposal is not None}"
                        )

                        if (
                            latest_proposal
                            and latest_proposal.created_at < timezone.now()
                        ):
                            is_confirmation = _message_is_user_confirmation(
                                message_text
                            )
                            logger.info(f"¿Es confirmación?: {is_confirmation}")

                            # Si el mensaje del usuario contiene confirmación, cerrar
                            if is_confirmation:
                                logger.info(
                                    f"Cerrando ticket {ticket.id} por confirmación de usuario"
                                )
                                # Generar resumen del ticket antes de cerrar
                                svc = TicketAIService()
                                ticket_summary = svc.generate_ticket_summary(ticket)

                                ticket.status = "Cerrado"
                                ticket.save()

                                # Crear mensaje de resumen y cierre
                                summary_text = ticket_summary or "Sin resumen generado."
                                TicketMessage.objects.create(
                                    ticket=ticket,
                                    sender="agent",
                                    message=f"✅ **Ticket Cerrado por Confirmación**\n\nEl usuario confirmó que el problema está resuelto.\n\n**RESUMEN FINAL:**\n{summary_text}",
                                )

                                # Escenario 6: ticket cerrado → email a usuario y soporte con resumen IA
                                try:
                                    EmailService.send_ticket_closed_to_all(ticket, summary_text)
                                except Exception as e_mail:
                                    logger.warning(f"Error enviando email de cierre: {e_mail}")

                                messages.success(
                                    request,
                                    "Gracias, por tu confirmación se ha cerrado el ticket.",
                                )
                                logger.info(f"Ticket {ticket.id} cerrado exitosamente")
                            else:
                                logger.info(
                                    "El mensaje no fue detectado como confirmación"
                                )
                                # Escenario 4: usuario responde sin confirmar → email a soporte
                                try:
                                    EmailService.send_user_reply_to_support(ticket, message_text)
                                except Exception as e_mail:
                                    logger.warning(f"Error enviando email a soporte: {e_mail}")
                        else:
                            if not latest_proposal:
                                logger.info("No hay propuesta de resolución previa")
                            else:
                                logger.warning(
                                    "La propuesta es más reciente que la hora actual"
                                )
                            # Escenario 4: usuario responde sin propuesta previa → email a soporte
                            try:
                                EmailService.send_user_reply_to_support(ticket, message_text)
                            except Exception as e_mail:
                                logger.warning(f"Error enviando email a soporte: {e_mail}")
                            # NOTA: La IA NO responde durante la conversación normal entre técnico y usuario
                            # para no interrumpir la comunicación. Solo interviene al crear el ticket o al cerrarlo.

                    except Exception as e:
                        logger.error("Error al procesar mensaje de usuario: %s", str(e))
                        messages.warning(
                            request,
                            "Tu mensaje fue guardado, pero la IA no pudo responder.",
                        )


            return redirect("ticket_detail", ticket_id=ticket_id)

    ticket_messages = ticket.messages.all()

    from app.iahelp.servicios.fondo import hay_trabajo_pendiente
    return render(
        request,
        "soporte/ticket_detail.html",
        {"ticket": ticket, "ticket_messages": ticket_messages,
         "analisis_pendiente": hay_trabajo_pendiente("ANALIZAR_TICKET", ticket.id)},
    )


@login_required
@permission_level_required(min_level=4, system="iahelp")
def support_dashboard(request):
    """Panel de soporte TI — muestra tickets activos del sistema (excluye cerrados)."""
    # Mostrar SOLO tickets activos (Abierto y En Progreso), excluyendo cerrados.
    tickets_qs = _con_ultimo_mensaje(
        Ticket.objects.filter(status__in=ESTADOS_ACTIVOS).order_by("-created_at"),
        TicketMessage,
    )
    tickets = _filas_tickets(tickets_qs, _leidos(request, staff=True))

    # Calcular stats generales
    abiertos_count = sum(1 for tk in tickets if tk["status"] == "Abierto")
    en_progreso_count = sum(1 for tk in tickets if tk["status"] == "En Progreso")
    critica_count = sum(1 for tk in tickets if tk["priority"] == "Crítica")
    urgente_count = sum(1 for tk in tickets if tk["priority"] == "Urgente")

    # Paginación de tarjetas (50/pág). KPIs intactos (lista completa).
    paginator = Paginator(tickets, TICKETS_POR_PAGINA)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "tickets": list(page_obj.object_list),
        "page_obj": page_obj,
        "total_tickets": len(tickets),
        "abiertos_count": abiertos_count,
        "en_progreso_count": en_progreso_count,
        "critica_count": critica_count,
        "urgente_count": urgente_count,
        "is_support": True,
    }

    return render(request, "soporte/support_dashboard.html", context)


def get_ticket_messages_api(request, ticket_id):
    """API endpoint para obtener mensajes actualizados de un ticket."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "No autenticado"}, status=401)

    try:
        ticket = Ticket.objects.get(id=ticket_id)

        # Verificar permisos: dueño o personal de soporte (nivel 4+)
        nivel_acceso = _nivel_acceso(request, "iahelp")
        is_support_staff = request.user.is_superuser or nivel_acceso >= 4
        if ticket.user != request.user and not is_support_staff:
            return JsonResponse({"error": "Sin permiso"}, status=403)

        messages_list = []
        for msg in ticket.messages.all().order_by("created_at"):
            sender_label, message_type = _clasificar_mensaje(msg, ticket)
            messages_list.append(
                {
                    "id": msg.id,
                    "sender": msg.sender,
                    "sender_label": sender_label,
                    "message": msg.message,
                    "message_type": message_type,
                    "created_at": msg.created_at.strftime("%d/%m/%Y %H:%M"),
                }
            )

        return JsonResponse(
            {
                "success": True,
                "messages": messages_list,
                "ticket_status": ticket.status,
                "ticket_id": ticket.id,
            }
        )

    except Ticket.DoesNotExist:
        return JsonResponse({"error": "Ticket no encontrado"}, status=404)
    except Exception as e:
        logger.error(f"Error en API get_ticket_messages: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def get_tickets_list_api(request):
    """API para obtener lista de tickets (usada para actualizaciones en tiempo real)."""
    try:
        # Solo niveles 4+ o admin real ven todo
        is_admin = _es_admin_real(request.user) or _nivel_acceso(request, "iahelp") >= 4

        if is_admin:
            tickets = Ticket.objects.filter(status__in=ESTADOS_ACTIVOS).order_by("-created_at")
        else:
            tickets = Ticket.objects.filter(
                user=request.user, status__in=ESTADOS_ACTIVOS
            ).order_by("-created_at")
        read_map = _leidos(request, staff=is_admin)

        # Tope anti-tormenta de polling (?limit=, 1..500, defecto 200). Forma intacta.
        try:
            _limit = int(request.GET.get("limit", "200"))
        except (TypeError, ValueError):
            _limit = 200
        _limit = max(1, min(_limit, 500))
        _rows = list(tickets[:_limit + 1])
        truncated = len(_rows) > _limit
        tickets = _rows[:_limit]

        # Lote único de mensajes agente/IA para unread (evita 2N queries)
        _ids = [t.id for t in tickets]
        _msgs = TicketMessage.objects.filter(
            ticket_id__in=_ids, sender__in=["agent", "ai"]
        ).values("ticket_id", "created_at")
        _por_ticket = {}
        for _m in _msgs:
            _por_ticket.setdefault(_m["ticket_id"], []).append(_m["created_at"])

        tickets_list = []
        for ticket in tickets:
            last_read_time = read_map.get(str(ticket.id))
            _cand = _por_ticket.get(ticket.id, [])
            if last_read_time:
                last_read = datetime.fromisoformat(last_read_time)
                has_unread = any(c > last_read for c in _cand)
            else:
                has_unread = bool(_cand)

            tickets_list.append(
                {
                    "id": ticket.id,
                    "title": ticket.title,
                    "status": ticket.status,
                    "priority": ticket.priority,
                    "nivel": ticket.nivel,
                    "usuario": ticket.usuario,
                    "created_at": ticket.created_at.strftime("%d/%m/%Y %H:%M"),
                    "ai_summary": ticket.ai_summary or "",
                    "unread": has_unread,
                }
            )

        return JsonResponse(
            {
                "success": True,
                "tickets": tickets_list,
                "count": len(tickets_list),
                "truncated": truncated,
            }
        )

    except Exception as e:
        logger.error(f"Error en API get_tickets_list: {e}")
        return JsonResponse({"error": str(e)}, status=500)


def get_unread_messages_count_api(request):
    """API endpoint para conteo de mensajes (retorna 0 - sin tracking de lectura)."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "No autenticado"}, status=401)

    # Ya no se usa unread count - retorna 0
    return JsonResponse(
        {
            "success": True,
            "unread_count": 0,
        }
    )


def mark_ticket_as_viewed_api(request, ticket_id):
    """API endpoint para marcar ticket como visto (ya no se usa - retorna success)."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "No autenticado"}, status=401)

    # Ya no se usa el tracking de lectura
    return JsonResponse(
        {
            "success": True,
            "ticket_id": ticket_id,
        }
    )


@login_required
def active_tickets(request):
    """Ver tickets abiertos/en progreso para personal de soporte."""
    # Solo niveles 4 y 5 o el admin real pueden ver todos los tickets
    is_admin = _es_admin_real(request.user) or _nivel_acceso(request, "iahelp") >= 4

    tickets_qs = Ticket.objects.filter(status__in=ESTADOS_ACTIVOS)
    if not is_admin:
        tickets_qs = tickets_qs.filter(user=request.user)

    q = (request.GET.get("q") or "").strip()
    if q:
        tickets_qs = tickets_qs.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(usuario__icontains=q)
        )

    filas = _filas_tickets(
        _con_ultimo_mensaje(tickets_qs.order_by("-created_at"), TicketMessage),
        _leidos(request, staff=is_admin),
        incluir_categoria=True,
    )

    # Los contadores se calculan sobre el total, no sobre la página visible.
    page_obj = _pagina_tickets(filas, request, por_pagina=TICKETS_POR_PAGINA)

    return render(
        request,
        "soporte/active_tickets.html",
        {
            "tickets": list(page_obj.object_list),
            "page_obj": page_obj,
            "abiertos_count": sum(1 for t in filas if t["status"] == "Abierto"),
            "en_progreso_count": sum(1 for t in filas if t["status"] == "En Progreso"),
            "q": q,
            "is_admin": is_admin,
        },
    )


@login_required
def closed_tickets(request):
    """Vista para mostrar tickets cerrados."""
    # Solo niveles 4 y 5 o el admin real pueden ver todos los tickets cerrados
    is_admin = _es_admin_real(request.user) or _nivel_acceso(request, "iahelp") >= 4

    if is_admin:
        tickets_list = Ticket.objects.filter(status="Cerrado").order_by("-created_at")
    else:
        tickets_list = Ticket.objects.filter(user=request.user, status="Cerrado").order_by(
            "-created_at"
        )

    return render(
        request,
        "soporte/closed_tickets.html",
        {
            "tickets": _pagina_tickets(tickets_list, request),
            "is_support": is_admin,
        },
    )


@require_http_methods(["GET"])
def api_closed_tickets(request):
    """API endpoint para obtener lista de tickets cerrados."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "No autenticado"}, status=401)

    try:
        # Aquí el criterio histórico es más amplio que en las vistas: basta
        # con ser staff de Django (no necesariamente el usuario `admin`).
        is_admin = _nivel_acceso(request, "iahelp") >= 4 or (
            request.user.is_superuser or request.user.is_staff
        )

        if is_admin:
            tickets_query = Ticket.objects.filter(status="Cerrado").order_by("-created_at")
        else:
            tickets_query = Ticket.objects.filter(
                user=request.user, status="Cerrado"
            ).order_by("-created_at")

        tickets = _pagina_tickets(tickets_query, request)

        tickets_list = [
            {
                "id": ticket.id,
                "title": ticket.title,
                "status": ticket.status,
                "priority": ticket.priority,
                "nivel": ticket.nivel,
                "usuario": ticket.usuario,
                "created_at": ticket.created_at.strftime("%d/%m/%Y %H:%M"),
                "updated_at": ticket.updated_at.strftime("%d/%m/%Y %H:%M"),
            }
            for ticket in tickets
        ]

        return JsonResponse(
            {
                "success": True,
                "tickets": tickets_list,
                "count": tickets.paginator.count,
            }
        )

    except Exception as e:
        logger.error(f"Error en API closed_tickets: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
@permission_level_required(min_level=1, system="iahelp") # Nivel 1 mínimo para responder
def api_responder_ticket(request, ticket_id):
    """
    Endpoint especializado para responder a un ticket vía API.
    Sustituye el guardado simple por una acción que dispara notificaciones.
    """
    try:
        data = json.loads(request.body)
        message_text = data.get("contenido", "").strip()

        if not message_text:
            return JsonResponse({"success": False, "error": "El contenido no puede estar vacío"}, status=400)

        ticket = Ticket.objects.get(id=ticket_id)

        # Verificar permisos específicos de este sistema
        is_support_staff = _es_admin_real(request.user) or _nivel_acceso(request, "iahelp") >= 4
        
        if ticket.user != request.user and not is_support_staff:
            return JsonResponse({"success": False, "error": "No autorizado"}, status=403)
            
        # Determinar remitente
        sender_type = "agent" if is_support_staff else "user"
        
        # 1. IA - Saludo empático si el ticket se reabre (usuario responde a ticket cerrado)
        if ticket.status == "Cerrado" and not is_support_staff:
            ticket.status = "Abierto"
            ticket.save()
            
            TicketMessage.objects.create(
                ticket=ticket,
                sender="system",
                message="[SISTEMA] Ticket reabierto por mensaje del usuario."
            )
            
            try:
                svc_ai = TicketAIService()
                reopen_greeting = svc_ai.generate_reopen_response(ticket, message_text)
                TicketMessage.objects.create(
                    ticket=ticket,
                    sender="agent",
                    message=f"[IA_REOPEN_GREETING]\n{reopen_greeting}"
                )
                
                # Notificar a soporte (Escenario 7)
                EmailService.send_ticket_reopened_to_support(ticket, message_text)
            except Exception as ai_e:
                logger.error(f"Error generando saludo de reapertura: {ai_e}")

        elif is_support_staff and ticket.status == "Abierto":
            ticket.status = "En Progreso"
            ticket.save()

        # Crear el mensaje
        message = TicketMessage.objects.create(
            ticket=ticket,
            sender=sender_type,
            message=message_text
        )
        
        # 2. IA - Detección de resolución (si responde agente)
        if is_support_staff:
            try:
                svc_ai = TicketAIService()
                res = svc_ai.detect_resolution(ticket, message_text)
                
                if res.get("is_resolved") and res.get("confidence") in ("alta", "media"):
                    closure_msg = svc_ai.generate_closure_message(ticket, res.get("solution_summary", ""))
                    proposal_text = "[RESOLUTION_PROPOSAL]\n" + closure_msg
                    
                    TicketMessage.objects.create(
                        ticket=ticket,
                        sender="agent",
                        message=proposal_text
                    )
                    
                    # Notificar al usuario (Escenario 5)
                    EmailService.send_resolution_proposal_to_user(ticket)
                else:
                    # Notificación estándar de respuesta (Escenario 3)
                    EmailService.send_ticket_response(ticket, message_text, request.user.username)
            except Exception as ai_e:
                logger.error(f"Error en detección de resolución IA: {ai_e}")
                # Fallback: notificación estándar
                EmailService.send_ticket_response(ticket, message_text, request.user.username)
        
        # 3. IA - Cierre automático por confirmación (si responde usuario)
        else:
            try:
                latest_proposal = _latest_resolution_proposal(ticket)
                if latest_proposal:
                    if _message_is_user_confirmation(message_text):
                        logger.info(f"Cerrando ticket {ticket.id} automáticamente por confirmación vía API")
                        
                        # Generar resumen IA para el cierre
                        try:
                            svc_ai = TicketAIService()
                            summary_text = svc_ai.generate_ticket_summary(ticket)
                            ticket.ai_summary = summary_text
                        except Exception as ai_e:
                            logger.error(f"Error generando resumen para cierre: {ai_e}")
                            summary_text = "Resumen no disponible."
                        
                        ticket.status = "Cerrado"
                        ticket.save()
                        
                        # Mensaje de sistema confirmando cierre
                        TicketMessage.objects.create(
                            ticket=ticket,
                            sender="agent",
                            message=f"✅ **Ticket Cerrado Automáticamente**\n\nEl usuario confirmó la resolución.\n\n**RESUMEN FINAL:**\n{summary_text}"
                        )
                        
                        # Notificar a todos (Escenario 6)
                        EmailService.send_ticket_closed_to_all(ticket, summary_text)
                    else:
                        # Si no confirma, notificar a soporte (Escenario 4)
                        EmailService.send_user_reply_to_support(ticket, message_text)
                else:
                    # Si no hay propuesta, notificar a soporte igualmente (Escenario 4)
                    EmailService.send_user_reply_to_support(ticket, message_text)
            except Exception as e_auto:
                logger.error(f"Error en procesamiento de cierre automático: {e_auto}")

        return JsonResponse({
            "success": True,
            "message_id": message.id,
            "ticket_status": ticket.status
        })
        
    except Ticket.DoesNotExist:
        return JsonResponse({"success": False, "error": "Ticket no encontrado"}, status=404)
    except Exception as e:
        logger.error(f"Error en api_responder_ticket: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
@permission_level_required(min_level=1, system="iahelp")
def api_cerrar_ticket(request, ticket_id):
    """
    Endpoint especializado para cerrar un ticket vía API.
    Cambia el estado a 'Cerrado' y dispara correos finales con resumen IA.
    """
    try:
        ticket = Ticket.objects.get(id=ticket_id)
        
        # Verificar permisos: solo soporte o el dueño del ticket pueden cerrar
        is_support_staff = request.user.is_superuser or request.user.is_staff
        
        if ticket.user != request.user and not is_support_staff:
            return JsonResponse({"success": False, "error": "No autorizado"}, status=403)
            
        if ticket.status == "Cerrado":
            return JsonResponse({"success": True, "message": "El ticket ya está cerrado"})

        # Generar resumen IA si no existe
        summary_text = ticket.ai_summary
        if not summary_text:
            try:
                svc = TicketAIService()
                summary_text = svc.generate_ticket_summary(ticket)
                ticket.ai_summary = summary_text
            except Exception as e:
                logger.error(f"Error generando resumen para cierre: {e}")
                summary_text = "Resumen no disponible."

        # Cerrar ticket
        ticket.status = "Cerrado"
        ticket.save()
        
        # Crear mensaje de sistema/cierre
        TicketMessage.objects.create(
            ticket=ticket,
            sender="agent" if is_support_staff else "user",
            message=f"🏁 **Ticket Cerrado Oficialmente**\n\nEl ticket ha sido marcado como resuelto.\n\n**RESUMEN FINAL:**\n{summary_text}"
        )
        
        # Enviar correo final (Escenario 6)
        try:
            EmailService.send_ticket_closed_to_all(ticket, summary_text)
            logger.info(f"Ticket {ticket.id} cerrado. Notificaciones enviadas.")
        except Exception as e:
            logger.error(f"Error enviando notificación de cierre: {e}")

        return JsonResponse({
            "success": True,
            "ticket_status": ticket.status,
            "ai_summary": summary_text
        })
        
    except Ticket.DoesNotExist:
        return JsonResponse({"success": False, "error": "Ticket no encontrado"}, status=404)
    except Exception as e:
        logger.error(f"Error en api_cerrar_ticket: {e}")
        return JsonResponse({"success": False, "error": str(e)}, status=500)
