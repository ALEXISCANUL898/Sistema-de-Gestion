"""Vistas de iahelp, agrupadas por dominio."""

from .autenticacion import (
    intranet_home,
    login_view,
    logout_view,
    index,
    dashboard,
)

from .tickets import (
    api_ticket_messages,
    ticket_detail,
    support_dashboard,
    get_ticket_messages_api,
    get_tickets_list_api,
    get_unread_messages_count_api,
    mark_ticket_as_viewed_api,
    active_tickets,
    closed_tickets,
    api_closed_tickets,
    api_responder_ticket,
    api_cerrar_ticket,
)

from .reportes import (
    reportes_view,
    exportar_reporte_excel,
    exportar_reporte_pdf,
)

from .chat_ia import (
    chat_ia_view,
    chat_ia_api,
)

from .econtrol import (
    econtrol_chat_ia_view,
    econtrol_chat_ia_api,
    econtrol_dashboard,
    econtrol_crear_ticket,
    econtrol_ver_ticket,
    econtrol_responder_ticket,
    econtrol_api_list,
    econtrol_api_detail,
    econtrol_soporte_dashboard,
    econtrol_cerrados_tickets,
    econtrol_api_closed,
    econtrol_cerrar_ticket,
    econtrol_reportes_view,
    econtrol_exportar_excel,
    econtrol_exportar_pdf,
)

__all__ = [
    "intranet_home",
    "login_view",
    "logout_view",
    "index",
    "dashboard",
    "api_ticket_messages",
    "ticket_detail",
    "support_dashboard",
    "get_ticket_messages_api",
    "get_tickets_list_api",
    "get_unread_messages_count_api",
    "mark_ticket_as_viewed_api",
    "active_tickets",
    "closed_tickets",
    "api_closed_tickets",
    "econtrol_chat_ia_view",
    "econtrol_chat_ia_api",
    "reportes_view",
    "exportar_reporte_excel",
    "exportar_reporte_pdf",
    "api_responder_ticket",
    "api_cerrar_ticket",
    "chat_ia_view",
    "chat_ia_api",
    "econtrol_dashboard",
    "econtrol_crear_ticket",
    "econtrol_ver_ticket",
    "econtrol_responder_ticket",
    "econtrol_api_list",
    "econtrol_api_detail",
    "econtrol_soporte_dashboard",
    "econtrol_cerrados_tickets",
    "econtrol_api_closed",
    "econtrol_cerrar_ticket",
    "econtrol_reportes_view",
    "econtrol_exportar_excel",
    "econtrol_exportar_pdf",
]
