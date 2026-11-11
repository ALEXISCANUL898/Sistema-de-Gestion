"""
Servicio de análisis de tickets con IA.

Centraliza las llamadas al modelo (AIClient) para clasificar tickets, generar
respuestas, resúmenes, detección de resolución, mensajes de cierre y
reapertura, además del registro de cada interacción en AiLog.
"""

import json
import logging

from django.conf import settings

from .cliente_ia import AIClient
from ..models import AiLog, EcontrolTicket, Ticket
from ..prompts import (
    TICKET_ANALYSIS_ENKONTROL_PROMPT,
    TICKET_ANALYSIS_PROMPT,
    TICKET_CLOSURE_ENKONTROL_PROMPT,
    TICKET_CLOSURE_PROMPT,
    TICKET_CONFIRMATION_ENKONTROL_PROMPT,
    TICKET_CONFIRMATION_PROMPT,
    TICKET_REPLY_ENKONTROL_PROMPT,
    TICKET_REPLY_PROMPT,
    TICKET_RESOLUTION_DETECTION_PROMPT,
    TICKET_RESOLUTION_ENKONTROL_PROMPT,
    TICKET_SUMMARY_ENKONTROL_PROMPT,
    TICKET_SUMMARY_PROMPT,
)

logger = logging.getLogger(__name__)

PRIORIDADES_VALIDAS = ("Crítica", "Urgente", "Alta", "Media", "Baja")


class TicketAIService:
    """Servicio centralizado para operaciones de IA sobre tickets."""

    def __init__(self):
        self.client = AIClient()

    def _registrar_log(self, prompt: str, respuesta: str, ticket=None) -> None:
        """Registra la interacción con la IA en AiLog, asociada al ticket si aplica."""
        if ticket is None:
            return

        log_kwargs = {
            "prompt": prompt,
            "ai_response": respuesta,
            "model_used": settings.AI_SETTINGS["MODEL"],
        }
        if isinstance(ticket, Ticket):
            log_kwargs["ticket"] = ticket
        elif isinstance(ticket, EcontrolTicket):
            log_kwargs["econtrol_ticket"] = ticket

        AiLog.objects.create(**log_kwargs)

    @staticmethod
    def _limpiar_bloque_markdown(raw: str, conservar_cierre: bool = False) -> str:
        """
        Quita los delimitadores ``` de una respuesta de la IA.

        Args:
            raw: Respuesta cruda del modelo.
            conservar_cierre: Si es True se descarta solo la primera línea y se
                eliminan los ``` restantes con un reemplazo global (comportamiento
                histórico de detect_resolution); si es False se descartan la
                primera y la última línea (comportamiento histórico de analyze).
        """
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if conservar_cierre:
                cleaned = "\n".join(lines[1:])
            else:
                # Se descartan la primera y la última línea (apertura y cierre).
                return "\n".join(lines[1:-1])

        if conservar_cierre:
            cleaned = cleaned.replace("```", "").strip()
        return cleaned

    def analyze(self, description: str, ticket=None, is_high_priority=False) -> dict:
        """
        Analiza la descripción de un ticket y devuelve clasificación IA.

        Args:
            description: Texto de la incidencia a analizar.
            ticket: Instancia de Ticket o EcontrolTicket opcional para registrar el log.
            is_high_priority: Booleano que indica si el usuario es VIP/Admin.

        Returns:
            dict con keys: category, nivel, priority, ai_summary, ai_suggested_response
        """
        is_econtrol = isinstance(ticket, EcontrolTicket)
        prompt = TICKET_ANALYSIS_ENKONTROL_PROMPT if is_econtrol else TICKET_ANALYSIS_PROMPT

        if is_high_priority:
            prompt += "\n\n[CONTEXTO IMPORTANTE]: Este ticket tiene ALTA PRIORIDAD por ser de un usuario con nivel administrativo."
            prompt += "\nREGLA CRÍTICA PARA ai_summary: NO menciones NUNCA el tipo de usuario, rol, nivel de acceso, ni palabras como 'superusuario', 'administrador', 'ejecutivo', 'nivel', 'rol', 'permisos'."

        raw_response = self.client.chat(prompt, description)
        self._registrar_log(f"[SYSTEM] {prompt}\n[USER] {description}", raw_response, ticket)

        # Parsear JSON de la respuesta
        try:
            result = json.loads(self._limpiar_bloque_markdown(raw_response))

            # Validar y establecer valores por defecto
            if "nivel" not in result:
                result["nivel"] = 1
            else:
                # Asegurar que nivel es un entero válido (1-4)
                try:
                    result["nivel"] = int(result["nivel"])
                    if result["nivel"] < 1 or result["nivel"] > 4:
                        result["nivel"] = 1
                except (ValueError, TypeError):
                    result["nivel"] = 1

            # Validar prioridad
            if result.get("priority") not in PRIORIDADES_VALIDAS:
                result["priority"] = "Media"

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error al parsear respuesta IA: %s — Raw: %s", e, raw_response)
            result = {
                "category": "General",
                "nivel": 2 if is_high_priority else 1,
                "priority": "Alta" if is_high_priority else "Media",
                "ai_summary": "No se pudo analizar automáticamente.",
                "ai_suggested_response": raw_response if raw_response else "Sin respuesta de IA.",
            }

        return result

    def generate_reply(self, ticket, user_message: str, is_high_priority=False, has_resolution_proposal=False) -> str:
        """
        Genera una respuesta IA para la conversación de un ticket.

        Args:
            ticket: Instancia del modelo Ticket o EcontrolTicket.
            user_message: Último mensaje del usuario.
            is_high_priority: Booleano que indica si el usuario es VIP/Admin.
            has_resolution_proposal: Booleano que indica si hay una propuesta de resolución pendiente.

        Returns:
            Texto de respuesta generado por la IA.
        """
        is_econtrol = isinstance(ticket, EcontrolTicket)

        # Si hay una propuesta de resolución pendiente, usar prompt especial de confirmación
        if has_resolution_proposal:
            if is_econtrol:
                system_prompt = TICKET_CONFIRMATION_ENKONTROL_PROMPT.format(
                    description=ticket.description,
                )
            else:
                system_prompt = TICKET_CONFIRMATION_PROMPT.format(
                    title=ticket.title,
                    description=ticket.description,
                )
        else:
            category = getattr(ticket, "category", "General")
            base_prompt = TICKET_REPLY_ENKONTROL_PROMPT if is_econtrol else TICKET_REPLY_PROMPT
            system_prompt = base_prompt.format(
                title=ticket.title,
                description=ticket.description,
                category=category,
                priority=ticket.priority,
            )

        if is_high_priority:
            system_prompt += "\n\n[CONTEXTO IMPORTANTE]: Prioridad alta. Mantén formato profesional."

        response = self.client.chat(system_prompt, user_message)
        self._registrar_log(
            f"[SYSTEM] {system_prompt}\n[USER] {user_message}", response, ticket
        )

        return response

    def generate_ticket_summary(self, ticket) -> str:
        """
        Genera un resumen completo del ticket antes de cerrarlo.

        Args:
            ticket: Instancia del modelo Ticket o EcontrolTicket.

        Returns:
            Texto de resumen generado por la IA.
        """
        is_econtrol = isinstance(ticket, EcontrolTicket)

        # Obtener todos los mensajes del ticket
        messages = ticket.messages.all().order_by("created_at")
        conversation = []
        for msg in messages:
            sender_display = "Usuario" if msg.sender == "user" else ("TI" if msg.sender == "agent" else "Sistema")
            conversation.append(f"{sender_display}: {msg.message}")

        conversation_text = "\n".join(conversation) if conversation else "Sin mensajes adicionales."
        category = getattr(ticket, "category", "General")

        base_prompt = TICKET_SUMMARY_ENKONTROL_PROMPT if is_econtrol else TICKET_SUMMARY_PROMPT
        prompt = base_prompt.format(
            ticket_id=ticket.id,
            title=ticket.title,
            description=ticket.description,
            category=category,
            priority=ticket.priority,
            status=ticket.status,
            created_at=ticket.created_at.strftime("%d/%m/%Y %H:%M"),
            conversation=conversation_text,
        )

        response = self.client.chat(prompt, "")
        self._registrar_log(f"[SYSTEM] {prompt}", response, ticket)

        return response

    def detect_resolution(self, ticket, tech_message: str) -> dict:
        """
        Detecta si un mensaje del técnico indica que el problema está resuelto.

        Args:
            ticket: Instancia del modelo Ticket o EcontrolTicket.
            tech_message: Mensaje del técnico a analizar.

        Returns:
            dict con keys: is_resolved, confidence, solution_summary, needs_user_confirmation
        """
        is_econtrol = isinstance(ticket, EcontrolTicket)

        if is_econtrol:
            # Historial simplificado para detección (se podría expandir si es necesario)
            prompt = TICKET_RESOLUTION_ENKONTROL_PROMPT.format(
                original_issue=ticket.description,
                module=getattr(ticket, "category", "Enkontrol"),
                message_history="",
                tech_message=tech_message,
            )
        else:
            prompt = TICKET_RESOLUTION_DETECTION_PROMPT.format(
                original_issue=ticket.description,
                tech_message=tech_message,
            )

        raw_response = self.client.chat(prompt, "")
        self._registrar_log(f"[SYSTEM] {prompt}", raw_response, ticket)

        try:
            cleaned = self._limpiar_bloque_markdown(raw_response, conservar_cierre=True)
            result = json.loads(cleaned)

            # Validar y normalizar campos obligatorios
            is_resolved = result.get("is_resolved", False)
            if isinstance(is_resolved, str):
                result["is_resolved"] = is_resolved.lower() == "true"
            else:
                result.setdefault("is_resolved", False)

            confidence = result.get("confidence", "baja")
            if isinstance(confidence, str):
                result["confidence"] = confidence.lower()
            else:
                result.setdefault("confidence", "baja")

            result.setdefault("solution_summary", "")
            result.setdefault("needs_user_confirmation", True)

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error al parsear resolución: %s — Raw: %s", e, raw_response)
            result = {
                "is_resolved": False,
                "confidence": "baja",
                "solution_summary": "",
                "needs_user_confirmation": True,
            }

        return result

    def generate_closure_message(self, ticket, solution_summary: str) -> str:
        """
        Genera un mensaje de cierre automático cuando se resuelve un ticket.

        Args:
            ticket: Instancia del modelo Ticket o EcontrolTicket.
            solution_summary: Resumen de la solución aplicada.

        Returns:
            Texto del mensaje de cierre.
        """
        is_econtrol = isinstance(ticket, EcontrolTicket)
        category = getattr(ticket, "category", "General")

        if is_econtrol:
            prompt = TICKET_CLOSURE_ENKONTROL_PROMPT.format(
                ticket_id=ticket.id,
                title=ticket.title,
                description=ticket.description,
                module=category,
                category=category,
                solution_summary=solution_summary,
                tech_name="Equipo de Soporte TI",
            )
        else:
            prompt = TICKET_CLOSURE_PROMPT.format(
                title=ticket.title,
                description=ticket.description,
                category=category,
                solution_summary=solution_summary,
            )

        response = self.client.chat("", prompt)
        self._registrar_log(f"[SYSTEM] {prompt}", response, ticket)

        return response

    def generate_reopen_response(self, ticket, user_message: str) -> str:
        """
        Genera un mensaje automático cuando un usuario reabre un ticket cerrado.

        Args:
            ticket: Instancia del modelo Ticket o EcontrolTicket.
            user_message: Mensaje del usuario indicando que el problema persiste.

        Returns:
            Texto del mensaje de reapertura.
        """
        category = getattr(ticket, "category", "No especificada")
        prompt = f"""Eres un asistente de soporte técnico profesional y empático.

Un usuario ha reabierto un ticket que estaba cerrado porque el problema ha vuelto a presentarse.

DATOS DEL TICKET:
- ID: #{ticket.id}
- Título: {ticket.title}
- Descripción original: {ticket.description}
- Categoría: {category}
- Prioridad: {ticket.priority}

MENSAJE DEL USUARIO:
{user_message}

INSTRUCCIONES:
1. Saluda al usuario de manera cordial
2. Reconoce que el problema ha vuelto a presentarse
3. Asegura que el equipo técnico revisará el caso nuevamente
4. Menciona que se le dará seguimiento prioritario
5. El mensaje debe ser breve (máximo 3-4 oraciones)
6. No uses emojis excesivos, máximo uno o dos
7. No menciones que eres una IA

RESPUESTA:"""

        response = self.client.chat(prompt, "")
        self._registrar_log(f"[SYSTEM] {prompt}", response, ticket)

        return response
