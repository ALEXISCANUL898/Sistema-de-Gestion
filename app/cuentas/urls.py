from django.urls import path
from . import views

app_name = "cuentas"

urlpatterns = [
    # ── Autenticación de cuenta ────────────────────────────────────────────────
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # ── Selección y cambio de perfil ───────────────────────────────────────────
    path("perfil/", views.seleccionar_perfil, name="seleccionar_perfil"),
    path("perfil/<int:perfil_id>/pin/", views.ingresar_pin, name="ingresar_pin"),
    path("perfil/cambiar/", views.cambiar_perfil, name="cambiar_perfil"),

    # ── API reautenticación con PIN (modales HTMX) ─────────────────────────────
    path("api/confirmar-pin/", views.confirmar_pin_api, name="confirmar_pin"),

    # ── Panel TI (Nivel 6) ─────────────────────────────────────────────────────
    path("ti/", views.ti_dashboard, name="ti_dashboard"),

    # Cuentas
    path("ti/cuentas/", views.ti_cuentas_list, name="ti_cuentas"),
    path("ti/cuentas/<int:user_id>/editar/", views.ti_cuenta_editar, name="ti_cuenta_editar"),

    # Perfiles
    path("ti/cuentas/<int:user_id>/perfiles/", views.ti_perfiles_list, name="ti_perfiles"),
    path("ti/cuentas/<int:user_id>/perfiles/nuevo/", views.ti_perfil_crear, name="ti_perfil_crear"),
    path("ti/perfiles/<int:perfil_id>/editar/", views.ti_perfil_editar, name="ti_perfil_editar"),
    path("ti/perfiles/<int:perfil_id>/pin/", views.ti_perfil_pin, name="ti_perfil_pin"),
    path("ti/perfiles/<int:perfil_id>/toggle/", views.ti_perfil_toggle, name="ti_perfil_toggle"),

    # ── Firmas privadas ────────────────────────────────────────────────────────
    path("firma/<path:path>", views.serve_firma, name="serve_firma"),
]
