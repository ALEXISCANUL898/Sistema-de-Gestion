"""
Servicio de envío de correos electrónicos para notificaciones.
7 escenarios de notificación del sistema Helpdesk AI.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

# Worker de envío en 2do plano: el request no espera al SMTP (antes bloqueaba
# segundos por cada correo). Sin dependencias nuevas; hilos daemon del proceso.
# Mismo contrato: True = aceptado para envío, False = error (ver logs).
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="smtp")


def _do_send(subject, message, from_email, recipients):
    send_mail(subject, message, from_email, recipients, fail_silently=False)
    return True

PREFIX = getattr(settings, 'EMAIL_SUBJECT_PREFIX', '[Helpdesk AI]')

ERP_ANALISTA_EMAIL = getattr(settings, 'EMAIL_ERP_ANALISTA', '')
SITE_URL = getattr(settings, 'SITE_URL', 'http://localhost:8000').rstrip('/')


def _support_email():
    """Retorna el email de soporte configurado en settings."""
    return getattr(settings, 'SUPPORT_EMAIL', settings.DEFAULT_FROM_EMAIL)


def _send(subject, message, recipients, ticket_id=None, cc_emails=None,
          etiqueta="Ticket #", incluir_analista_erp=False):
    """Encola un correo en 2do plano y registra el resultado.

    `cc_emails` añade destinatarios en copia; `incluir_analista_erp` añade
    siempre al analista ERP configurado en settings.
    """
    try:
        recipients = list(recipients)
        if incluir_analista_erp and ERP_ANALISTA_EMAIL and ERP_ANALISTA_EMAIL not in recipients:
            recipients.append(ERP_ANALISTA_EMAIL)
        for cc in cc_emails or ():
            if cc and cc not in recipients:
                recipients.append(cc)

        fut = _POOL.submit(
            _do_send, subject, message, settings.DEFAULT_FROM_EMAIL, recipients,
        )

        def _done(f, _tag=f"{etiqueta}{ticket_id} — " if ticket_id else "", _rcp=recipients):
            try:
                f.result()
                logger.info(f"{_tag}Correo enviado a {_rcp}")
            except Exception as e:
                logger.error(f"Error al enviar correo a {_rcp}: {e}")

        fut.add_done_callback(_done)
        return True
    except Exception as e:
        logger.error(f"Error al encolar correo a {recipients}: {e}")
        return False


class EmailService:
    """Servicio centralizado de notificaciones por correo."""

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 1 — Ticket creado: confirmación al usuario
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_ticket_created_to_user(ticket):
        """Escenario 1: Confirma al usuario que su ticket fue recibido."""
        if not ticket.email:
            logger.warning(f"Ticket #{ticket.id} sin email — no se envía notificación al usuario")
            return False

        message = f"""Estimado/a {ticket.usuario},

Su solicitud de soporte ha sido recibida exitosamente.

━━━ Detalles del ticket ━━━
• ID:          #{ticket.id}
• Título:      {ticket.title}
• Descripción: {ticket.description}
• Prioridad:   {ticket.priority}
• Estado:      {ticket.status}

Nuestro equipo de TI atenderá su solicitud a la brevedad posible.

Ver mi ticket:
{SITE_URL}/ticket/{ticket.id}/

Saludos,
Equipo de TI
"""
        return _send(
            f"{PREFIX} Ticket #{ticket.id} creado — {ticket.title}",
            message,
            [ticket.email],
            ticket.id,
        )

    # Alias para compatibilidad con el código existente
    send_ticket_createdNotification = send_ticket_created_to_user

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 2 — Ticket creado: alerta a soporte con resumen IA
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_new_ticket_to_support(ticket):
        """Escenario 2: Notifica a soporte de un nuevo ticket con resumen IA."""
        ai_summary = ticket.ai_summary or "Análisis de IA no disponible."

        message = f"""Equipo de TI,

Se ha creado un nuevo ticket de soporte que requiere atención.

━━━ Detalles del ticket ━━━
• ID:          #{ticket.id}
• Título:      {ticket.title}
• Descripción: {ticket.description}
• Prioridad:   {ticket.priority}
• Nivel:       {ticket.nivel}
• Usuario:     {ticket.usuario}
• Email:       {ticket.email or 'No registrado'}

━━━ Resumen de IA ━━━
{ai_summary}

Puede atender el ticket directamente aquí:
{SITE_URL}/ticket/{ticket.id}/

Por favor, acceda al sistema para atender este ticket.

Saludos,
Equipo de TI
"""
        return _send(
            f"{PREFIX} Nuevo Ticket #{ticket.id} [{ticket.priority}] — {ticket.title}",
            message,
            [_support_email()],
            ticket.id,
        )

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 3 — Soporte responde: notificación al usuario
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_ticket_response(ticket, response_message, agente_nombre=None):
        """Escenario 3: Notifica al usuario que soporte respondió su ticket."""
        if not ticket.email:
            logger.warning(f"Ticket #{ticket.id} sin email — no se envía respuesta al usuario")
            return False

        agente = agente_nombre or "Equipo de TI"
        message = f"""Estimado/a {ticket.usuario},

El equipo de soporte ha respondido a su ticket.

━━━ Detalles del ticket ━━━
• ID:     #{ticket.id}
• Título: {ticket.title}
• Estado: {ticket.status}

━━━ Respuesta de {agente} ━━━
{response_message}

Puede ver todos los detalles y responder aquí:
{SITE_URL}/ticket/{ticket.id}/

Puede ingresar al sistema para responder o ver más detalles.

Saludos,
Equipo de TI
"""
        return _send(
            f"{PREFIX} Ticket #{ticket.id} — Nueva respuesta del equipo de TI",
            message,
            [ticket.email],
            ticket.id,
        )

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 4 — Usuario responde: alerta a soporte
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_user_reply_to_support(ticket, user_message):
        """Escenario 4: Notifica a soporte que el usuario respondió."""
        message = f"""Equipo de TI,

El usuario ha enviado un nuevo mensaje en el ticket #{ticket.id}.

━━━ Detalles del ticket ━━━
• ID:      #{ticket.id}
• Título:  {ticket.title}
• Estado:  {ticket.status}
• Usuario: {ticket.usuario}

━━━ Mensaje del usuario ━━━
{user_message}

Ver conversación completa:
{SITE_URL}/ticket/{ticket.id}/

Por favor, acceda al sistema para revisar y responder.

Saludos,
Equipo de TI
"""
        return _send(
            f"{PREFIX} Ticket #{ticket.id} — Nuevo mensaje del usuario {ticket.usuario}",
            message,
            [_support_email()],
            ticket.id,
        )

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 5 — Propuesta de resolución: usuario debe confirmar
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_resolution_proposal_to_user(ticket):
        """Escenario 5: Informa al usuario que soporte propuso cerrar el ticket y necesita confirmación."""
        if not ticket.email:
            logger.warning(f"Ticket #{ticket.id} sin email — no se envía propuesta al usuario")
            return False

        message = f"""Estimado/a {ticket.usuario},

El equipo de TI considera que su problema ha sido resuelto y ha enviado una propuesta de cierre para el ticket #{ticket.id}.

━━━ Detalles del ticket ━━━
• ID:     #{ticket.id}
• Título: {ticket.title}
• Estado: {ticket.status}

Para confirmar que su problema ha sido resuelto, responda al ticket con alguna de estas palabras:
  → "Confirmado", "Sí funciona", "Gracias", "Listo", "Resuelto"

Si el problema persiste, describa qué sigue fallando en su respuesta.

El ticket se cerrará automáticamente si no recibe respuesta en 24 horas.

Saludos,
Equipo de TI
"""
        return _send(
            f"{PREFIX} Ticket #{ticket.id} — ¿Se resolvió su problema? Confirme por favor",
            message,
            [ticket.email],
            ticket.id,
        )

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 6 — Ticket cerrado: notificación a usuario y soporte con resumen IA
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_ticket_closed_to_all(ticket, ai_summary=None):
        """Escenario 6: Notifica el cierre del ticket con resumen IA al usuario y a soporte."""
        resumen = ai_summary or ticket.ai_summary or "Resumen no disponible."
        resultados = []

        # Al usuario
        if ticket.email:
            msg_usuario = f"""Estimado/a {ticket.usuario},

Su ticket ha sido cerrado exitosamente.

━━━ Detalles del ticket ━━━
• ID:     #{ticket.id}
• Título: {ticket.title}
• Estado: Cerrado

━━━ Resumen de la resolución ━━━
{resumen}

Si necesita asistencia adicional, puede abrir un nuevo ticket.

Saludos,
Equipo de TI
"""
            resultados.append(
                _send(
                    f"{PREFIX} Ticket #{ticket.id} cerrado — {ticket.title}",
                    msg_usuario,
                    [ticket.email],
                    ticket.id,
                )
            )
        else:
            logger.warning(f"Ticket #{ticket.id} sin email — no se notifica cierre al usuario")

        # A soporte
        msg_soporte = f"""Equipo de TI,

El ticket #{ticket.id} ha sido cerrado.

━━━ Detalles del ticket ━━━
• ID:      #{ticket.id}
• Título:  {ticket.title}
• Usuario: {ticket.usuario}
• Email:   {ticket.email or 'No registrado'}

━━━ Resumen final ━━━
{resumen}

Saludos,
Equipo de TI
"""
        resultados.append(
            _send(
                f"{PREFIX} Ticket #{ticket.id} cerrado — {ticket.title}",
                msg_soporte,
                [_support_email()],
                ticket.id,
            )
        )

        return all(resultados)

    # Alias para compatibilidad con código existente
    @staticmethod
    def send_ticket_closed(ticket):
        return EmailService.send_ticket_closed_to_all(ticket)

    # ──────────────────────────────────────────────────────────────
    # ESCENARIO 7 — Ticket reabierto: alerta a soporte
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def send_ticket_reopened_to_support(ticket, user_message=None):
        """Escenario 7: Notifica a soporte que un ticket cerrado fue reabierto."""
        detalle_mensaje = f"\n━━━ Mensaje del usuario ━━━\n{user_message}" if user_message else ""

        message = f"""Equipo de TI,

Un ticket que estaba cerrado ha sido reabierto por el usuario.

━━━ Detalles del ticket ━━━
• ID:      #{ticket.id}
• Título:  {ticket.title}
• Usuario: {ticket.usuario}
• Estado:  {ticket.status}
{detalle_mensaje}

Por favor, revise el caso en el sistema.

Saludos,
Equipo de TI
"""
        return _send(
            f"{PREFIX} Ticket #{ticket.id} reabierto — {ticket.usuario}",
            message,
            [_support_email()],
            ticket.id,
        )


class EnkontrolEmailService:
    """Servicio de notificaciones por correo para tickets Enkontrol."""

    @staticmethod
    def _fetch_nivel5_emails_from_api():
        """
        Consulta la API central para obtener los emails de todos los usuarios
        con nivel de acceso 5 en el sistema Enkontrol (código '002').
        Retorna una lista de emails o [] si no se puede contactar la API.
        """
        import requests as http_requests

        base = getattr(settings, 'AUTH_SERVER_URL', '').rstrip('/')
        api_key = getattr(settings, 'INTERNAL_API_KEY', '')
        if not base or not api_key:
            return []

        headers = {'X-Internal-API-Key': api_key}

        candidate_endpoints = [
            '/api/permisos/analistas/',
            '/api/permisos/usuarios/?sistema_codigo=002&nivel_acceso=5',
        ]

        for endpoint in candidate_endpoints:
            try:
                resp = http_requests.get(
                    base + endpoint,
                    headers=headers,
                    timeout=4,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # La respuesta puede ser una lista o un dict con una clave de lista
                    if isinstance(data, list):
                        users = data
                    elif isinstance(data, dict):
                        # Buscar la primera clave que sea lista (ej: "emails": [...])
                        users = next(
                            (v for v in data.values() if isinstance(v, list)),
                            []
                        )
                    else:
                        continue

                    emails_api = []
                    for u in users:
                        if isinstance(u, str):
                            # Si la lista ya contiene strings (ej. los emails directamente)
                            if u:
                                emails_api.append(u)
                        elif isinstance(u, dict):
                            # Si es una lista de objetos usuario
                            email = (
                                u.get('email') or
                                u.get('user_email') or
                                (u.get('user') or {}).get('email') or
                                ''
                            )
                            nivel = (
                                u.get('nivel_acceso') or
                                u.get('nivel') or
                                (u.get('rol') or {}).get('nivel_acceso') or
                                5 # Asumimos 5 si el endpoint ya filtra
                            )
                            # Incluir si nivel 5 o si el endpoint ya filtró
                            if email and (int(nivel) >= 5 or not nivel):
                                emails_api.append(email)

                    if emails_api:
                        logger.info(f"API central devolvió {len(emails_api)} analistas nivel 5: {emails_api}")
                        return emails_api

                elif resp.status_code == 404:
                    # Endpoint no existe, probar el siguiente
                    continue
                else:
                    logger.warning(f"API central respondió {resp.status_code} en {endpoint}")
            except Exception as e:
                logger.debug(f"No se pudo consultar {endpoint}: {e}")
                continue

        logger.warning("No se encontró endpoint en API central para usuarios nivel 5 de Enkontrol.")
        return []

    @staticmethod
    def get_analyst_emails(ticket):
        """
        Retorna la lista de emails a los que deben llegar las notificaciones
        de tickets Enkontrol:
          1. email_analista_erp del ticket (si existe)
          2. Usuarios nivel 5 del sistema Enkontrol consultados en la API central
          3. Fallback a DB local si la API no responde (usuarios ya sincronizados)
          4. Fallback final al SUPPORT_EMAIL si nada funciona
        """
        from ..models import UsuarioSistema
        emails = []

        # 1. Email analista ERP del ticket
        if ticket.email_analista_erp and ticket.email_analista_erp not in emails:
            emails.append(ticket.email_analista_erp)

        # 2. Consultar la API central — nivel 5, sistema Enkontrol (código 002)
        api_ok = False
        try:
            api_emails = EnkontrolEmailService._fetch_nivel5_emails_from_api()
            for em in api_emails:
                if em and em not in emails:
                    emails.append(em)
            api_ok = bool(api_emails)
        except Exception as e:
            logger.error(f"Error consultando API central para nivel 5 Enkontrol: {e}")

        # 3. Fallback DB local cuando la API no respondió o no devolvió usuarios
        if not api_ok:
            try:
                us_nivel5 = UsuarioSistema.objects.filter(
                    rol__nivel_acceso=5, sistema__codigo='002'
                ).select_related('user')
                for us in us_nivel5:
                    if us.user.email and us.user.email not in emails:
                        emails.append(us.user.email)
            except Exception as e:
                logger.error(f"Error obteniendo analistas nivel 5 de Enkontrol desde DB local: {e}")

        # 4. Fallback final: SUPPORT_EMAIL
        if not emails:
            support = _support_email()
            if support:
                emails.append(support)
            logger.warning("Sin analistas nivel 5 disponibles — usando SUPPORT_EMAIL como fallback.")

        return emails

    @staticmethod
    def send_ticket_created_to_user(ticket):
        """Confirma al usuario Enkontrol que su ticket fue recibido."""
        if not ticket.email:
            logger.warning(f"ENKONTROL-#{ticket.id} sin email — no se envía notificación")
            return False

        message = f"""Estimado/a {ticket.usuario},

Su solicitud de soporte ENKONTROL ha sido recibida exitosamente.

━━━ Detalles del ticket ━━━
• ID:          #{ticket.id}
• Título:      {ticket.title}
• Descripción: {ticket.description}
• Prioridad:   {ticket.priority}
• Estado:      {ticket.status}

Nuestro equipo de soporte atenderá su solicitud a la brevedad posible.

Ver mi ticket Enkontrol:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Saludos,
Equipo de Soporte Enkontrol
"""
        return _send(
            f"[ENKONTROL] Ticket #{ticket.id} creado — {ticket.title}",
            message,
            [ticket.email],
            ticket.id,
        )

    @staticmethod
    def send_new_ticket_to_support(ticket):
        """Notifica a soporte de un nuevo ticket Enkontrol con resumen IA."""
        ai_summary = ticket.ai_summary or "Análisis de IA no disponible."

        message = f"""Equipo de Soporte Enkontrol,

Se ha creado un nuevo ticket ENKONTROL que requiere atención.

━━━ Detalles del ticket ━━━
• ID:          #{ticket.id}
• Título:      {ticket.title}
• Descripción: {ticket.description}
• Prioridad:   {ticket.priority}
• Nivel:       {ticket.nivel}
• Usuario:     {ticket.usuario}
• Email:       {ticket.email or 'No registrado'}
• Email Analista ERP: {ticket.email_analista_erp or 'No registrado'}

━━━ Resumen de IA ━━━
{ai_summary}

Atender incidencia Enkontrol:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Por favor, acceda al sistema para atender este ticket.

Saludos,
Equipo de Soporte Enkontrol
"""
        analysts = EnkontrolEmailService.get_analyst_emails(ticket)
        return _send(
            f"[ENKONTROL] Nuevo Ticket #{ticket.id} [{ticket.priority}] — {ticket.title}",
            message,
            analysts if analysts else [_support_email()],
            ticket.id,
            etiqueta="ENKONTROL-#",
            incluir_analista_erp=True,
        )

    @staticmethod
    def send_ticket_response(ticket, response_message, agente_nombre=None):
        """Notifica al usuario Enkontrol que soporte respondió su ticket."""
        if not ticket.email:
            logger.warning(f"ENKONTROL-#{ticket.id} sin email — no se envía respuesta")
            return False

        agente = agente_nombre or "Equipo de Soporte Enkontrol"
        message = f"""Estimado/a {ticket.usuario},

El equipo de soporte ha respondido a su ticket ENKONTROL.

━━━ Detalles del ticket ━━━
• ID:     #{ticket.id}
• Título: {ticket.title}
• Estado: {ticket.status}

━━━ Respuesta de {agente} ━━━
{response_message}

Puede ver todos los detalles y responder aquí:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Puede ingresar al sistema para responder o ver más detalles.

Saludos,
Equipo de Soporte Enkontrol
"""
        return _send(
            f"[ENKONTROL] Ticket #{ticket.id} — Nueva respuesta del equipo de soporte",
            message,
            [ticket.email],
            ticket.id,
        )

    @staticmethod
    def send_user_reply_to_support(ticket, user_message):
        """Notifica a soporte que el usuario Enkontrol respondió."""
        message = f"""Equipo de Soporte Enkontrol,

El usuario ha enviado un nuevo mensaje en el ticket ENKONTROL #{ticket.id}.

━━━ Detalles del ticket ━━━
• ID:      #{ticket.id}
• Título:  {ticket.title}
• Estado:  {ticket.status}
• Usuario: {ticket.usuario}

━━━ Mensaje del usuario ━━━
{user_message}

Ver conversación completa:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Por favor, acceda al sistema para revisar y responder.

Saludos,
Equipo de Soporte Enkontrol
"""
        analysts = EnkontrolEmailService.get_analyst_emails(ticket)
        return _send(
            f"[ENKONTROL] Ticket #{ticket.id} — Nuevo mensaje del usuario {ticket.usuario}",
            message,
            analysts if analysts else [_support_email()],
            ticket.id,
            etiqueta="ENKONTROL-#",
            incluir_analista_erp=True,
        )

    @staticmethod
    def send_ticket_closed_to_all(ticket, ai_summary=None):
        """Notifica el cierre del ticket Enkontrol al usuario y a soporte."""
        resumen = ai_summary or ticket.ai_summary or "Resumen no disponible."
        resultados = []

        if ticket.email:
            msg_usuario = f"""Estimado/a {ticket.usuario},

Su ticket ENKONTROL ha sido cerrado exitosamente.

━━━ Detalles del ticket ━━━
• ID:     #{ticket.id}
• Título: {ticket.title}
• Estado: Cerrado

━━━ Resumen de la resolución ━━━
{resumen}

Si necesita asistencia adicional, puede abrir un nuevo ticket.

Ver detalles finales:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Saludos,
Equipo de Soporte Enkontrol
"""
            resultados.append(
                _send(
                    f"[ENKONTROL] Ticket #{ticket.id} cerrado — {ticket.title}",
                    msg_usuario,
                    [ticket.email],
                    ticket.id,
                )
            )

        msg_soporte = f"""Equipo de Soporte Enkontrol,

El ticket ENKONTROL #{ticket.id} ha sido cerrado.

━━━ Detalles del ticket ━━━
• ID:      #{ticket.id}
• Título:  {ticket.title}
• Usuario: {ticket.usuario}
• Email:   {ticket.email or 'No registrado'}
• Email Analista ERP: {ticket.email_analista_erp or 'No registrado'}

━━━ Resumen final ━━━
{resumen}

Ver ticket cerrado:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Saludos,
Equipo de Soporte Enkontrol
"""
        analysts = EnkontrolEmailService.get_analyst_emails(ticket)
        resultados.append(
            _send(
                f"[ENKONTROL] Ticket #{ticket.id} cerrado — {ticket.title}",
                msg_soporte,
                analysts if analysts else [_support_email()],
                ticket.id,
                etiqueta="ENKONTROL-#",
                incluir_analista_erp=True,
            )
        )

        return all(resultados)

    @staticmethod
    def send_ticket_reopened_to_support(ticket, user_message=None):
        """Notifica a soporte que un ticket Enkontrol cerrado fue reabierto."""
        detalle_mensaje = f"\n━━━ Mensaje del usuario ━━━\n{user_message}" if user_message else ""

        message = f"""Equipo de Soporte Enkontrol,

Un ticket ENKONTROL que estaba cerrado ha sido reabierto por el usuario.

━━━ Detalles del ticket ━━━
• ID:      #{ticket.id}
• Título:  {ticket.title}
• Usuario: {ticket.usuario}
• Estado:  {ticket.status}
{detalle_mensaje}

Ver ticket reabierto:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Por favor, revise el caso en el sistema.

Saludos,
Equipo de Soporte Enkontrol
"""
        analysts = EnkontrolEmailService.get_analyst_emails(ticket)
        return _send(
            f"[ENKONTROL] Ticket #{ticket.id} reabierto — {ticket.usuario}",
            message,
            analysts if analysts else [_support_email()],
            ticket.id,
            etiqueta="ENKONTROL-#",
            incluir_analista_erp=True,
        )

    @staticmethod
    def send_resolution_proposal_to_user(ticket):
        """Informa al usuario Enkontrol que soporte propuso cerrar el ticket."""
        if not ticket.email:
            logger.warning(f"ENKONTROL-#{ticket.id} sin email — no se envía propuesta")
            return False

        message = f"""Estimado/a {ticket.usuario},

El equipo de soporte considera que su problema ENKONTROL ha sido resuelto y ha enviado una propuesta de cierre para el ticket #{ticket.id}.

━━━ Detalles del ticket ━━━
• ID:     #{ticket.id}
• Título: {ticket.title}
• Estado: {ticket.status}

Para confirmar que su problema ha sido resuelto, responda al ticket con alguna de estas palabras:
  → "Confirmado", "Sí funciona", "Gracias", "Listo", "Resuelto"

Si el problema persiste, describa qué sigue fallando en su respuesta.

El ticket se cerrará automáticamente si no recibe respuesta en 24 horas.

Responder al ticket aquí:
{SITE_URL}/econtrol/ticket/{ticket.id}/

Saludos,
Equipo de Soporte Enkontrol
"""
        return _send(
            f"[ENKONTROL] Ticket #{ticket.id} — ¿Se resolvió su problema? Confirme por favor",
            message,
            [ticket.email],
            ticket.id,
        )

    @staticmethod
    def send_ticket_closed(ticket):
        """Alias para send_ticket_closed_to_all."""
        return EnkontrolEmailService.send_ticket_closed_to_all(ticket)
