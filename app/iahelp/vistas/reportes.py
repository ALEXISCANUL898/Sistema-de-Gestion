"""Reportes y exportaciones de los tickets de IA Help."""

import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render

from ..infraestructura.decoradores import permission_level_required
from ..models import Ticket

from .comunes import (
    _es_admin_real,
    _fechas_de_reporte,
    _horas_promedio_resolucion,
    _nivel_acceso,
    _rango_fechas_reporte,
)

logger = logging.getLogger(__name__)

# REPORTES Y ESTADÍSTICAS

@login_required
@permission_level_required(min_level=4, system="iahelp")
def reportes_view(request):
    """Vista para generar y visualizar reportes de tickets."""
    fecha_inicio, fecha_fin, inicio, fin = _rango_fechas_reporte(request)

    # Consultas base
    tickets_base = Ticket.objects.filter(created_at__gte=inicio, created_at__lte=fin)

    # Estadísticas generales (1 query agregada en vez de 13 count())
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

    # Por categoría
    categorias = tickets_base.values("category").annotate(count=Count("id")).order_by("-count")

    context = {
        **estadisticas,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "categorias": list(categorias)[:10],
        "tiempo_promedio": _horas_promedio_resolucion(tickets_base),
    }

    return render(request, "soporte/reportes.html", context)


@login_required
def exportar_reporte_excel(request):
    """Exporta tickets filtrados a un archivo Excel."""
    is_admin = _es_admin_real(request.user) or _nivel_acceso(request, "iahelp") >= 4

    if not is_admin:
        return JsonResponse({"error": "No autorizado"}, status=403)

    try:
        import pandas as pd
        from django.http import HttpResponse

        fechas = _fechas_de_reporte(request)
        if not fechas:
            return JsonResponse({"error": "Fechas requeridas"}, status=400)
        fecha_inicio, fecha_fin, inicio, fin = fechas

        tickets = Ticket.objects.filter(created_at__gte=inicio, created_at__lte=fin).order_by("-created_at")[:5000]

        data = [
            {
                "ID": t.id,
                "Título": t.title,
                "Usuario": t.usuario,
                "Email": t.email or "",
                "Categoría": t.category or "",
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
        response["Content-Disposition"] = f"attachment; filename=reporte_tickets_{fecha_inicio}_{fecha_fin}.xlsx"
        df.to_excel(response, index=False, engine="openpyxl")

        return response
    except Exception as e:
        logger.error(f"Error al exportar Excel: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def exportar_reporte_pdf(request):
    """Exporta tickets filtrados a un archivo PDF."""
    is_admin = _es_admin_real(request.user) or _nivel_acceso(request, "iahelp") >= 4

    if not is_admin:
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

        tickets = Ticket.objects.filter(created_at__gte=inicio, created_at__lte=fin)[:100]
        
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename=reporte_tickets_{fecha_inicio}_{fecha_fin}.pdf"
        
        doc = SimpleDocTemplate(response, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph(f"Reporte de Tickets - {fecha_inicio} a {fecha_fin}", styles["Title"]))
        elements.append(Spacer(1, 0.25 * inch))
        
        data = [["ID", "Título", "Usuario", "Nivel", "Prioridad", "Estado"]]
        for t in tickets:
            data.append([
                str(t.id),
                t.title[:30] + "..." if len(t.title) > 30 else t.title,
                t.usuario[:15],
                f"Nivel {t.nivel}",
                t.priority,
                t.status
            ])
        
        table = Table(data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        elements.append(table)
        doc.build(elements)
        
        return response
    except Exception as e:
        logger.error(f"Error al exportar PDF: {e}")
        return JsonResponse({"error": str(e)}, status=500)
