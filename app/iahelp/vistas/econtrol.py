"""Vistas y API del sistema Enkontrol."""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..infraestructura.decoradores import permission_level_required
from ..models import EcontrolTicket, EcontrolTicketMessage
from ..prompts import CHAT_ENKONTROL_PROMPT
from ..servicios.correo import EnkontrolEmailService
from ..servicios.datos_enkontrol import CATEGORIES_LIST
from ..servicios.ia_tickets import TicketAIService

from .comunes import (
    _con_ultimo_mensaje,
    _contexto_tickets,
    _econtrol_auto_close_expired_proposal,
    _econtrol_latest_resolution_proposal,
    _es_admin_real,
    _exigir_permiso_enkontrol,
    _fechas_de_reporte,
    _filas_tickets,
    _horas_promedio_resolucion,
    _leidos,
    _marcar_leido,
    _message_is_user_confirmation,
    _nivel_acceso,
    _pagina_tickets,
    _rango_fechas_reporte,
    _responder_chat_ia,
    _tiene_no_leidos,
)

logger = logging.getLogger(__name__)

# ENKONTROL - CHAT IA PARA REPORTE

@login_required
def econtrol_chat_ia_view(request):
    """Chat libre con IA para generar reportes y analizar datos de Enkontrol."""
    is_support = request.user.is_superuser or request.user.is_staff
    
    if not is_support:
        return redirect("econtrol_dashboard")
    
    return render(request, "econtrol/chat_ia.html")


@login_required
@permission_level_required(min_level=5, system="enkontrol")
def econtrol_chat_ia_api(request):
    """API para procesar mensajes del chat IA de Enkontrol."""
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"error": "No autorizado"}, status=403)

    def construir_prompt():
        contexto = _contexto_tickets(
            EcontrolTicket.objects.all().order_by("-created_at")[:50],
            "Tickets recientes de Enkontrol:",
        )
        return CHAT_ENKONTROL_PROMPT.format(contexto=contexto)

    return _responder_chat_ia(request, construir_prompt, " Enkontrol")


@login_required
def econtrol_dashboard(request):
    """Dashboard principal para sección Enkontrol (Lado Usuario)."""
    # 1. Verificar permiso específico en la sesión para ENKONTROL
    error_permiso = _exigir_permiso_enkontrol(request, " Sesión invalidada.")
    if error_permiso:
        return error_permiso

    nivel_acceso = _nivel_acceso(request, "enkontrol")

    # 2. Redirigir al panel de soporte SOLO si tiene nivel 4+ en Enkontrol
    if _es_admin_real(request.user) or nivel_acceso >= 4:
        return redirect("econtrol_soporte_dashboard")

    # Base QuerySet para el usuario
    base_tickets = EcontrolTicket.objects.filter(user=request.user)

    # Contadores (1 query agregada)
    contadores = base_tickets.aggregate(
        abiertos=Count("id", filter=Q(status='Abierto')),
        en_progreso=Count("id", filter=Q(status='En Progreso')),
        cerrados=Count("id", filter=Q(status='Cerrado')),
    )

    # Separar activos de cerrados para el dashboard
    context = {
        **contadores,
        'tickets': base_tickets.filter(status__in=['Abierto', 'En Progreso']).order_by('-created_at')[:20],
        'tickets_cerrados': base_tickets.filter(status='Cerrado').order_by('-created_at')[:5],
    }
    return render(request, 'econtrol/dashboard.html', context)


@login_required
def econtrol_crear_ticket(request):
    """Crear nuevo ticket Enkontrol (paridad con IA Help)."""
    # 1. Verificar permiso específico en la sesión para ENKONTROL
    error_permiso = _exigir_permiso_enkontrol(request)
    if error_permiso:
        return error_permiso

    nivel_acceso = _nivel_acceso(request, "enkontrol")

    # 2. Redirigir al soporte si es nivel 4+
    if _es_admin_real(request.user) or nivel_acceso >= 4:
        return redirect("econtrol_soporte_dashboard")

    ticket = None
    nivel_usuario = nivel_acceso
    is_support = nivel_usuario >= 4
    
    if request.method == 'POST':
        titulo = request.POST.get('titulo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        categoria_post = request.POST.get('categoria', '').strip()
        
        # Obtener email del usuario
        user_email = request.POST.get('email', '').strip()
        if not user_email:
            user_email = request.user.email if request.user.email else ''
        
        # Si se proporcionó un email y difiere del que tiene el usuario, actualizarlo
        if user_email and request.user.email != user_email:
            User.objects.filter(id=request.user.id).update(email=user_email)
            request.user.email = user_email
        
        email_analista_erp = getattr(settings, 'EMAIL_ERP_ANALISTA', '')
        
        if not titulo or not descripcion:
            messages.error(request, 'El título y descripción son obligatorios.')
            context = {
                'ticket': ticket,
                'email_user': user_email,
                'email_analista_erp': email_analista_erp,
                'categorias': CATEGORIES_LIST,
                'is_support': is_support,
            }
            return render(request, 'econtrol/crear_ticket.html', context)
        
        # El nivel_usuario ya fue obtenido al inicio

        ticket = EcontrolTicket.objects.create(
            user=request.user,
            title=titulo,
            description=descripcion,
            usuario=request.user.first_name if request.user.first_name else request.user.username,
            email=user_email,
            email_analista_erp=email_analista_erp,
            priority='Media',
            status='Abierto',
            nivel=1, # Temporal
            nivel_usuario=nivel_usuario,
        )
        
        # Análisis IA: en fondo si el worker vive, sincrónico si no (etapa 4C).
        from app.iahelp.servicios.fondo import (
            cola_viva, encolar_analisis_econtrol, aplicar_analisis_econtrol,
        )
        if cola_viva():
            encolar_analisis_econtrol(ticket.id, nivel_usuario, categoria_post)
            messages.success(request, f'Ticket ENKONTROL-#{ticket.id} recibido. La IA lo está clasificando.')
        else:
            # Analizar con IA
            try:
                is_specialist = nivel_usuario >= 3
                svc = TicketAIService()
                analysis = svc.analyze(descripcion, ticket=ticket, is_high_priority=is_specialist)

                ai_nivel = aplicar_analisis_econtrol(ticket, analysis, nivel_usuario, categoria_post)

                messages.success(request, f'Ticket ENKONTROL-#{ticket.id} creado y clasificado como Nivel {ai_nivel}.')
            except Exception as e:
                logger.error("Error al analizar ticket Enkontrol con IA: %s", str(e))
                messages.warning(request, "Ticket creado, pero el análisis de IA falló.")

        # Enviar correos: escenario 1 (usuario) + escenario 2 (soporte)
        try:
            EnkontrolEmailService.send_ticket_created_to_user(ticket)
            EnkontrolEmailService.send_new_ticket_to_support(ticket)
        except Exception as e:
            logger.warning(f"No se pudo enviar notificación por correo: {e}")
    context = {
        'ticket': ticket,
        'email_user': getattr(request.user, 'email', ''),
        'email_analista_erp': getattr(settings, 'EMAIL_ERP_ANALISTA', ''),
        'categorias': CATEGORIES_LIST,
        'is_support': is_support,
    }
    return render(request, 'econtrol/crear_ticket.html', context)


@login_required
def econtrol_ver_ticket(request, ticket_id):
    """Ver detalle de ticket Enkontrol (con tracking de lectura)."""
    try:
        ticket = EcontrolTicket.objects.get(id=ticket_id)
    except EcontrolTicket.DoesNotExist:
        messages.error(request, 'Ticket no encontrado.')
        return redirect('econtrol_dashboard')
    
    is_support = request.user.is_superuser or request.user.is_staff
    
    if ticket.user != request.user and not is_support:
        messages.error(request, 'No tienes permiso para ver este ticket.')
        return redirect('econtrol_dashboard')
    
    # Marcar como leído
    _marcar_leido(request, ticket_id, staff=is_support, sufijo="_econtrol")
    
    # Comprobar cierre automático de propuestas
    try:
        _econtrol_auto_close_expired_proposal(ticket)
    except Exception:
        logger.exception("Error al comprobar cierre automático de propuestas Enkontrol")
    
    mensajes = ticket.messages.all().order_by('created_at')

    from app.iahelp.servicios.fondo import hay_trabajo_pendiente
    context = {
        'ticket': ticket,
        'mensajes': mensajes,
        'is_support': is_support,
        'analisis_pendiente': hay_trabajo_pendiente("ANALIZAR_ECONTROL", ticket.id),
    }
    return render(request, 'econtrol/detalle_ticket.html', context)


@login_required
def econtrol_responder_ticket(request, ticket_id):
    """Responder a un ticket Enkontrol con lógica de IA paritaria."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        ticket = EcontrolTicket.objects.get(id=ticket_id)
    except EcontrolTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket no encontrado'}, status=404)
    
    message_text = request.POST.get('message', '').strip()
    if not message_text:
        return JsonResponse({'error': 'El mensaje no puede estar vacío'}, status=400)
    
    is_support = request.user.is_superuser or request.user.is_staff
    
    sender = 'agent' if is_support else 'user'
    
    # 1. Guardar mensaje principal
    EcontrolTicketMessage.objects.create(
        ticket=ticket,
        sender=sender,
        message=message_text,
    )
    
    # 2. Lógica para Agente de Soporte
    if is_support:
        # Si es mensaje de soporte, asegurar que el estado sea En Progreso
        if ticket.status not in ("En Progreso", "Cerrado"):
            ticket.status = "En Progreso"
            ticket.save()
            
        # Detectar si el técnico resolvió el problema (IA)
        try:
            svc = TicketAIService()
            resolution_analysis = svc.detect_resolution(ticket, message_text)
            
            logger.info(f"Resolución detectada para ENKONTROL-{ticket.id}: {resolution_analysis}")

            if resolution_analysis.get("is_resolved") and resolution_analysis.get("confidence") in ("alta", "media"):
                closure_message = svc.generate_closure_message(
                    ticket, resolution_analysis.get("solution_summary", "Problema resuelto")
                )
                proposal_text = "[RESOLUTION_PROPOSAL]\n" + closure_message

                EcontrolTicketMessage.objects.create(
                    ticket=ticket,
                    sender="agent",
                    message=proposal_text,
                )
                
                logger.info(f"Propuesta de cierre creada para ENKONTROL-{ticket.id}")
                
                # Enviar email de propuesta (Escenario 5)
                EnkontrolEmailService.send_resolution_proposal_to_user(ticket)
            else:
                # Si NO se detectó resolución, enviar notificación estándar (Escenario 3)
                EnkontrolEmailService.send_ticket_response(ticket, message_text, request.user.username)
        except Exception as e:
            logger.error("Error al detectar resolución Enkontrol: %s", str(e))
            # Fallback: enviar notificación estándar
            try:
                EnkontrolEmailService.send_ticket_response(ticket, message_text, request.user.username)
            except Exception as email_e:
                logger.warning(f"Error al enviar notificación Enkontrol: {email_e}")

    # 3. Lógica para Usuario
    else:
        # Si el ticket está cerrado, reabrirlo (IA)
        if ticket.status == "Cerrado":
            ticket.status = "Abierto"
            ticket.save()

            try:
                svc = TicketAIService()
                reopen_response = svc.generate_reopen_response(ticket, message_text)
                
                EcontrolTicketMessage.objects.create(
                    ticket=ticket,
                    sender="agent",
                    message=f"[TICKET_REABIERTO]\n{reopen_response}",
                )
                
                # Notificar a soporte (Escenario 7)
                EnkontrolEmailService.send_ticket_reopened_to_support(ticket, message_text)
            except Exception as e:
                logger.error("Error en reapertura Enkontrol: %s", str(e))
                EcontrolTicketMessage.objects.create(
                    ticket=ticket,
                    sender="agent",
                    message="[TICKET_REABIERTO] Hemos recibido tu mensaje. El seguimiento continuará.",
                )

        # Comprobar si confirma una propuesta previa
        else:
            try:
                latest_proposal = _econtrol_latest_resolution_proposal(ticket)
                
                if latest_proposal:
                    if _message_is_user_confirmation(message_text):
                        # Generar resumen final y cerrar
                        svc = TicketAIService()
                        summary = svc.generate_ticket_summary(ticket)
                        
                        ticket.status = "Cerrado"
                        ticket.save()
                        
                        resumen_texto = summary or "Solución confirmada por usuario."
                        
                        EcontrolTicketMessage.objects.create(
                            ticket=ticket,
                            sender="agent",
                            message=f"✅ **Ticket de Enkontrol Solucionado**\n\nEl usuario confirmó que la solución es correcta.\n\n**RESUMEN FINAL:**\n{resumen_texto}",
                        )
                        
                        # Notificar a todos (Escenario 6)
                        EnkontrolEmailService.send_ticket_closed(ticket)
                    else:
                        # Usuario responde pero no confirma resolución (Escenario 4)
                        EnkontrolEmailService.send_user_reply_to_support(ticket, message_text)
                else:
                    # No hay propuesta previa, solo notificar a soporte (Escenario 4)
                    EnkontrolEmailService.send_user_reply_to_support(ticket, message_text)
            except Exception as e:
                logger.error("Error al procesar mensaje usuario Enkontrol: %s", str(e))
    
    return JsonResponse({'success': True, 'message': 'Respuesta procesada correctamente'})


@login_required
def econtrol_api_list(request):
    """API para listar tickets Enkontrol en JSON (con unread status)."""
    is_support = request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 4

    if is_support:
        tickets_qs = _con_ultimo_mensaje(
            EcontrolTicket.objects.filter(status__in=["Abierto", "En Progreso"]).order_by("-created_at"),
            EcontrolTicketMessage,
        )
    else:
        # Para el usuario devolvemos activos y cerrados recientes por separado o en una lista procesable
        tickets_qs = _con_ultimo_mensaje(
            EcontrolTicket.objects.filter(user=request.user).order_by("-created_at"),
            EcontrolTicketMessage,
        )
    read_map = _leidos(request, staff=is_support, sufijo="_econtrol")

    def process_ticket(t):
        return {
            'id': t.id,
            'usuario': t.usuario,
            'title': t.title,
            'description': t.description[:100] if t.description else "",
            'priority': t.priority,
            'category': t.category or "Sin clasificar",
            'status': t.status,
            'nivel': t.nivel,
            'created_at': t.created_at.strftime('%d/%m/%Y %H:%M'),
            'unread': _tiene_no_leidos(t, read_map),
        }

    tickets_activos = []
    tickets_cerrados = []

    for t in tickets_qs:
        ticket_data = process_ticket(t)
        if t.status == 'Cerrado':
            tickets_cerrados.append(ticket_data)
        else:
            tickets_activos.append(ticket_data)

    # Limitar cerrados para el dashboard si no es vista completa
    if not is_support:
        tickets_cerrados = tickets_cerrados[:5]

    # Calcular counts para el dashboard
    counts = {}
    if is_support:
        counts = EcontrolTicket.objects.filter(status__in=["Abierto", "En Progreso"]).aggregate(
            total_activos=Count("id"),
            abiertos=Count("id", filter=Q(status='Abierto')),
            en_progreso=Count("id", filter=Q(status='En Progreso')),
            criticos=Count("id", filter=Q(priority='Crítica')),
        )

    # Counts para el usuario (siempre se devuelven para su dashboard)
    user_counts = EcontrolTicket.objects.filter(user=request.user).aggregate(
        abiertos=Count("id", filter=Q(status='Abierto')),
        en_progreso=Count("id", filter=Q(status='En Progreso')),
        cerrados=Count("id", filter=Q(status='Cerrado')),
    )

    return JsonResponse({
        'success': True,
        'tickets': tickets_activos,
        'tickets_cerrados': tickets_cerrados,
        'counts': counts,
        'user_counts': user_counts
    })


@login_required
def econtrol_api_detail(request, ticket_id):
    """API para obtener detalle de ticket Enkontrol en JSON."""
    try:
        ticket = EcontrolTicket.objects.get(id=ticket_id)
    except EcontrolTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket no encontrado'}, status=404)
    
    is_support = request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 4

    if ticket.user != request.user and not is_support:
        return JsonResponse({'error': 'Sin permiso'}, status=403)
    
    mensajes = ticket.messages.all().order_by('created_at')
    
    data = {
        'id': ticket.id,
        'title': ticket.title,
        'description': ticket.description,
        'priority': ticket.priority,
        'category': ticket.category or "Sin clasificar",
        'status': ticket.status,
        'nivel': ticket.nivel,
        'usuario': ticket.usuario,
        'email': ticket.email,
        'email_analista_erp': ticket.email_analista_erp,
        'ai_summary': ticket.ai_summary,
        'created_at': ticket.created_at.strftime('%d/%m/%Y %H:%M'),
        'updated_at': ticket.updated_at.strftime('%d/%m/%Y %H:%M'),
        'messages': [{
            'sender': m.sender,
            'message': m.message,
            'created_at': m.created_at.strftime('%d/%m/%Y %H:%M'),
        } for m in mensajes],
    }
    
    return JsonResponse(data)


@login_required
@permission_level_required(min_level=4, system="enkontrol")
def econtrol_soporte_dashboard(request):
    """Dashboard para el analista ERP con tickets de Enkontrol (paridad con IA Help)."""
    tickets_qs = _con_ultimo_mensaje(
        EcontrolTicket.objects.filter(status__in=["Abierto", "En Progreso"]).order_by("-created_at"),
        EcontrolTicketMessage,
    )

    # Lecturas por sesión (para unread)
    read_map = _leidos(request, staff=True, sufijo="_econtrol")
    tickets_list = _filas_tickets(tickets_qs, read_map, incluir_categoria=True)

    # Calcular stats (1 query agregada)
    estadisticas = EcontrolTicket.objects.aggregate(
        abiertos_count=Count("id", filter=Q(status='Abierto')),
        en_progreso_count=Count("id", filter=Q(status='En Progreso')),
        critica_count=Count("id", filter=Q(priority='Crítica', status__in=['Abierto', 'En Progreso'])),
    )

    # Paginación (50/pág). KPIs intactos (lista completa).
    paginator = Paginator(tickets_list, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        **estadisticas,
        'total_activos': estadisticas['abiertos_count'] + estadisticas['en_progreso_count'],
        'tickets': list(page_obj.object_list),
        'page_obj': page_obj,
        'is_support': True,
    }
    return render(request, 'econtrol/soporte_dashboard.html', context)


@login_required
def econtrol_cerrados_tickets(request):
    """Vista para mostrar tickets Enkontrol cerrados."""
    is_support = request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 3

    if is_support:
        tickets_list = EcontrolTicket.objects.filter(status='Cerrado').order_by('-created_at')
    else:
        tickets_list = EcontrolTicket.objects.filter(user=request.user, status='Cerrado').order_by('-created_at')

    return render(request, 'econtrol/cerrados_tickets.html', {
        'tickets': _pagina_tickets(tickets_list, request),
        'is_support': is_support,
    })


@login_required
def econtrol_api_closed(request):
    """API endpoint para tickets Enkontrol cerrados."""
    is_support = request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 3

    if is_support:
        tickets_query = EcontrolTicket.objects.filter(status='Cerrado').order_by('-created_at')
    else:
        tickets_query = EcontrolTicket.objects.filter(user=request.user, status='Cerrado').order_by('-created_at')

    tickets = _pagina_tickets(tickets_query, request)

    data = [{
        'id': t.id,
        'title': t.title,
        'usuario': t.usuario,
        'category': t.category or "Sin clasificar",
        'nivel': t.nivel,
        'priority': t.priority,
        'status': t.status,
        'created_at': t.created_at.strftime('%d/%m/%Y'),
        'updated_at': t.updated_at.strftime('%d/%m/%Y') if t.updated_at else '',
    } for t in tickets]

    return JsonResponse({'success': True, 'tickets': data, 'count': tickets.paginator.count})


@login_required
def econtrol_cerrar_ticket(request, ticket_id):
    """Cerrar un ticket Enkontrol vía AJAX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        ticket = EcontrolTicket.objects.get(id=ticket_id)
    except EcontrolTicket.DoesNotExist:
        return JsonResponse({'error': 'Ticket no encontrado'}, status=404)
    
    is_support = request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 3

    if ticket.user != request.user and not is_support:
        return JsonResponse({'error': 'Sin permiso'}, status=403)
    
    ticket.status = 'Cerrado'
    ticket.save()
    
    EcontrolTicketMessage.objects.create(
        ticket=ticket,
        sender='system',
        message='🏁 **Ticket Cerrado Oficialmente**\n\nEl ticket ha sido marcado como resuelto.'
    )
    
    # Notificar cierre a usuario y soporte (Escenario 6)
    try:
        EnkontrolEmailService.send_ticket_closed(ticket)
    except Exception as e:
        logger.warning(f"Error al enviar notificación de cierre ENKONTROL: {e}")
    
    return JsonResponse({'success': True, 'message': 'Ticket cerrado correctamente'})


@login_required
@permission_level_required(min_level=4, system="enkontrol")
def econtrol_reportes_view(request):
    """Panel de reportes para Enkontrol."""
    fecha_inicio, fecha_fin, inicio, fin = _rango_fechas_reporte(request)

    tickets_base = EcontrolTicket.objects.filter(created_at__gte=inicio, created_at__lte=fin)

    # Estadísticas (1 query agregada en vez de 13 count())
    estadisticas = tickets_base.aggregate(
        total_tickets=Count("id"),
        abiertos=Count("id", filter=Q(status="Abierto")),
        en_progreso=Count("id", filter=Q(status="En Progreso")),
        cerrados=Count("id", filter=Q(status="Cerrado")),
        nivel_1=Count("id", filter=Q(nivel=1)),
        nivel_2=Count("id", filter=Q(nivel=2)),
        nivel_3=Count("id", filter=Q(nivel=3)),
        nivel_4=Count("id", filter=Q(nivel=4)),
        prioridad_critica=Count("id", filter=Q(priority="Crítica")),
        prioridad_urgente=Count("id", filter=Q(priority="Urgente")),
        prioridad_alta=Count("id", filter=Q(priority="Alta")),
        prioridad_media=Count("id", filter=Q(priority="Media")),
        prioridad_baja=Count("id", filter=Q(priority="Baja")),
    )

    context = {
        **estadisticas,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "tiempo_promedio": _horas_promedio_resolucion(tickets_base),
    }

    return render(request, "econtrol/reportes.html", context)


@login_required
def econtrol_exportar_excel(request):
    """Exporta reporte de tickets Enkontrol a Excel."""
    if not (request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 3):
        return JsonResponse({"error": "No autorizado"}, status=403)

    try:
        import pandas as pd
        from django.http import HttpResponse

        fechas = _fechas_de_reporte(request)
        if not fechas:
            return JsonResponse({"error": "Fechas requeridas"}, status=400)
        fecha_inicio, fecha_fin, inicio, fin = fechas

        tickets = EcontrolTicket.objects.filter(created_at__gte=inicio, created_at__lte=fin).order_by("-created_at")[:5000]

        data = [
            {
                "ID": f"ENKONTROL-{t.id}",
                "Título": t.title,
                "Usuario": t.usuario,
                "Email": t.email or "",
                "Analista ERP": t.email_analista_erp or "",
                "Nivel": t.nivel,
                "Prioridad": t.priority,
                "Estado": t.status,
                "Creado": t.created_at.strftime("%Y-%m-%d %H:%M"),
                "Actualizado": t.updated_at.strftime("%Y-%m-%d %H:%M") if t.updated_at else "",
            }
            for t in tickets
        ]
        
        df = pd.DataFrame(data)
        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f"attachment; filename=reporte_econtrol_{fecha_inicio}_{fecha_fin}.xlsx"
        df.to_excel(response, index=False, engine="openpyxl")
        return response
    except Exception as e:
        logger.error(f"Error al exportar Excel Enkontrol: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def econtrol_exportar_pdf(request):
    """Exporta reporte de tickets Enkontrol a PDF."""
    if not (request.user.is_superuser or _nivel_acceso(request, "enkontrol") >= 3):
        return JsonResponse({"error": "No autorizado"}, status=403)

    try:
        from django.http import HttpResponse
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch

        fechas = _fechas_de_reporte(request)
        if not fechas:
            return JsonResponse({"error": "Fechas requeridas"}, status=400)
        fecha_inicio, fecha_fin, inicio, fin = fechas

        tickets = EcontrolTicket.objects.filter(created_at__gte=inicio, created_at__lte=fin)[:100]
        
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename=reporte_econtrol_{fecha_inicio}_{fecha_fin}.pdf"
        
        doc = SimpleDocTemplate(response, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph(f"Reporte de Tickets Enkontrol - {fecha_inicio} a {fecha_fin}", styles["Title"]))
        elements.append(Spacer(1, 0.25 * inch))
        
        data = [["ID", "Título", "Usuario", "Nivel", "Prioridad", "Estado"]]
        for t in tickets:
            data.append([
                f"EC-{t.id}",
                t.title[:30] + "..." if len(t.title) > 30 else t.title,
                t.usuario[:15],
                f"Nivel {t.nivel}",
                t.priority,
                t.status
            ])
        
        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.navy),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        elements.append(table)
        doc.build(elements)
        return response
    except Exception as e:
        logger.error(f"Error al exportar PDF Enkontrol: {e}")
        return JsonResponse({"error": str(e)}, status=500)
