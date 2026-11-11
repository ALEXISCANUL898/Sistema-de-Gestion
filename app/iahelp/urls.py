from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from app.cuentas.api_views import VerificarPinView

from .api.vistas import LoginView, MisSistemasView, ValidarPermisoView
from .vistas.autenticacion import dashboard, index, intranet_home, login_view, logout_view
from .vistas.chat_ia import chat_ia_api, chat_ia_view
from .vistas.econtrol import (
    econtrol_api_closed,
    econtrol_api_detail,
    econtrol_api_list,
    econtrol_cerrar_ticket,
    econtrol_cerrados_tickets,
    econtrol_chat_ia_api,
    econtrol_chat_ia_view,
    econtrol_crear_ticket,
    econtrol_dashboard,
    econtrol_exportar_excel,
    econtrol_exportar_pdf,
    econtrol_responder_ticket,
    econtrol_reportes_view,
    econtrol_soporte_dashboard,
    econtrol_ver_ticket,
)
from .vistas.reportes import (
    exportar_reporte_excel,
    exportar_reporte_pdf,
    reportes_view,
)
from .vistas.tickets import (
    active_tickets,
    api_cerrar_ticket,
    api_closed_tickets,
    api_responder_ticket,
    closed_tickets,
    get_ticket_messages_api,
    get_tickets_list_api,
    get_unread_messages_count_api,
    mark_ticket_as_viewed_api,
    support_dashboard,
    ticket_detail,
)

urlpatterns = [
    path("", intranet_home, name="intranet_home"),
    path("login/", login_view, {"system": "iahelp"}, name="login"),
    path("econtrol/login/", login_view, {"system": "enkontrol"}, name="econtrol_login"),
    path("reservaciones/login/", login_view, {"system": "reservaciones"}, name="reservas_login"),
    path("intranet/login/", login_view, {"system": "intranet"}, name="intranet_login"),
    path("prestamos/login/", login_view, {"system": "PRESTAMOS"}, name="prestamos_login"),
    path("almacen/login/", login_view, {"system": "Almacen"}, name="almacen_login"),
    path("catalogos/login/", login_view, {"system": "Catalogos"}, name="catalogos_login"),
    path("logout/", logout_view, name="logout"),
    path("crear-ticket/", index, name="iahelp"),
    path("dashboard/", dashboard, name="listikets"),
    path("soporte/", support_dashboard, name="support_dashboard"),
    path("ticket/<int:ticket_id>/", ticket_detail, name="ticket_detail"),
    path("activos/", active_tickets, name="active_tickets"),
    # API Endpoints
    path("api/permisos/login/", LoginView.as_view(), name="api_login"),
    path(
        "api/permisos/validar-permiso/",
        ValidarPermisoView.as_view(),
        name="api_validar_permiso",
    ),
    path(
        "api/permisos/mis-sistemas/", MisSistemasView.as_view(), name="api_mis_sistemas"
    ),
    path(
        "api/permisos/verificar-pin/",
        VerificarPinView.as_view(),
        name="api_verificar_pin",
    ),
    path(
        "api/permisos/token/refresh/",
        TokenRefreshView.as_view(),
        name="api_token_refresh",
    ),
    # API Endpoints para actualizaciones en tiempo real
    path("api/tickets/<int:ticket_id>/messages/", get_ticket_messages_api, name="api_ticket_messages"),
    path("api/tickets/list/", get_tickets_list_api, name="api_tickets_list"),
    path("api/tickets/unread-count/", get_unread_messages_count_api, name="api_unread_count"),
    path("api/tickets/<int:ticket_id>/mark-viewed/", mark_ticket_as_viewed_api, name="api_mark_ticket_viewed"),
    path("api/tickets/closed/", api_closed_tickets, name="api_closed_tickets"),
    path("cerrados/", closed_tickets, name="cerrados_tickets"),
    # Reportes
    path("reportes/", reportes_view, name="reportes"),
    path("reportes/exportar/excel/", exportar_reporte_excel, name="exportar_excel"),
    path("reportes/exportar/pdf/", exportar_reporte_pdf, name="exportar_pdf"),
    # Chat IA
    path("chat-ia/", chat_ia_view, name="chat_ia"),
    path("api/chat-ia/", chat_ia_api, name="chat_ia_api"),
    # Nuevos endpoints especializados
    path("api/tickets/<int:ticket_id>/responder/", api_responder_ticket, name="api_responder_ticket"),
    path("api/tickets/<int:ticket_id>/cerrar/", api_cerrar_ticket, name="api_cerrar_ticket"),
    # Econtrol
    path("econtrol/", econtrol_dashboard, name="econtrol_dashboard"),
    path("econtrol/soporte/", econtrol_soporte_dashboard, name="econtrol_soporte_dashboard"),
    path("econtrol/crear/", econtrol_crear_ticket, name="econtrol_crear_ticket"),
    path("econtrol/ticket/<int:ticket_id>/", econtrol_ver_ticket, name="econtrol_ver_ticket"),
    path("econtrol/api/tickets/", econtrol_api_list, name="econtrol_api_list"),
    path("econtrol/api/ticket/<int:ticket_id>/", econtrol_api_detail, name="econtrol_api_detail"),
    path("econtrol/api/ticket/<int:ticket_id>/responder/", econtrol_responder_ticket, name="econtrol_responder_ticket"),
    path("econtrol/api/ticket/<int:ticket_id>/cerrar/", econtrol_cerrar_ticket, name="econtrol_cerrar_ticket"),
    path("econtrol/reportes/", econtrol_reportes_view, name="econtrol_reportes"),
    path("econtrol/reportes/exportar/excel/", econtrol_exportar_excel, name="econtrol_exportar_excel"),
    path("econtrol/reportes/exportar/pdf/", econtrol_exportar_pdf, name="econtrol_exportar_pdf"),
    path("econtrol/cerrados/", econtrol_cerrados_tickets, name="econtrol_cerrados_tickets"),
    path("econtrol/api/tickets/closed/", econtrol_api_closed, name="econtrol_api_closed"),
    path("econtrol/chat-ia/", econtrol_chat_ia_view, name="econtrol_chat_ia"),
    path("econtrol/api/chat-ia/", econtrol_chat_ia_api, name="econtrol_chat_ia_api"),
]
