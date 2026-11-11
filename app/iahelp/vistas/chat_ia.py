"""Chat libre con IA del Helpdesk."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from ..infraestructura.decoradores import permission_level_required
from ..models import Ticket
from ..prompts import CHAT_SOPORTE_PROMPT

from .comunes import _contexto_tickets, _responder_chat_ia

# CHAT IA PARA REPORTE

@login_required
@permission_level_required(min_level=5, system="iahelp")
def chat_ia_view(request):
    """Chat libre con IA para generar reportes y analizar datos."""
    return render(request, "soporte/chat_ia.html")


@login_required
@permission_level_required(min_level=5, system="iahelp")
def chat_ia_api(request):
    """API para procesar mensajes del chat IA."""
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({"error": "No autorizado"}, status=403)

    def construir_prompt():
        contexto = _contexto_tickets(
            Ticket.objects.all().order_by("-created_at")[:50],
            "Tickets recientes del sistema:",
        )
        return CHAT_SOPORTE_PROMPT.format(contexto=contexto)

    return _responder_chat_ia(request, construir_prompt)
