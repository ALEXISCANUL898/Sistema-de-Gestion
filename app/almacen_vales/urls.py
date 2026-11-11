from django.urls import path
from . import views, views_ti
from app.catalogos.views import material_buscar

app_name = "almacen"

urlpatterns = [
    # ── Solicitante (Nivel 1) ─────────────────────────────────────────────────
    path("mis-vales/", views.mis_vales_list, name="mis_vales"),
    path("materiales/buscar/", material_buscar, name="material_buscar"),
    path("vales/nuevo/", views.vale_create, name="vale_create"),
    path("vales/crear-y-emitir/", views.vale_create_emitir, name="vale_create_emitir"),
    path("vales/<int:pk>/", views.vale_detalle, name="vale_detalle"),
    path("vales/<int:pk>/imprimir/", views.vale_imprimir, name="vale_imprimir"),
    path("vales/<int:pk>/editar/", views.vale_editar, name="vale_editar"),
    path("vales/<int:pk>/descartar/", views.vale_descartar, name="vale_descartar"),
    path("vales/<int:pk>/firmar/", views.vale_firmar, name="vale_firmar"),
    path("vales/<int:pk>/solicitar-anulacion/", views.solicitud_anulacion, name="solicitud_anulacion"),

    # ── Almacén (Nivel 3) ─────────────────────────────────────────────────────
    path("bandeja/", views.bandeja_almacen, name="bandeja"),
    path("exportar-entregas/", views.exportar_entregas_excel, name="exportar_entregas"),
    path("vales/<int:pk>/atencion/", views.almacen_detalle, name="panel_detalle"),
    path("vales/<int:pk>/asignar/", views.vale_asignar, name="vale_asignar"),
    path("vales/<int:pk>/despachar/", views.vale_despachar, name="vale_despachar"),
    path("vales/<int:pk>/cerrar/", views.vale_cerrar, name="vale_cerrar"),
    path("vales/<int:pk>/cerrar-faltante/", views.vale_cerrar_faltante, name="vale_cerrar_faltante"),
    path("vales/<int:pk>/entregas/<int:entrega_id>/anular/", views.entrega_anular, name="entrega_anular"),

    # ── Gerencia (Nivel 4) ────────────────────────────────────────────────────
    path("gerencia/dashboard/", views.dashboard_gerencia, name="dashboard_gerencia"),
    path("gerencia/excepciones/", views.reporte_excepciones, name="reporte_excepciones"),

    # ── Panel TI (Nivel 6) ────────────────────────────────────────────────────
    path("ti/vales-eliminados/", views_ti.vales_eliminados, name="vales_eliminados"),
    path("ti/vales/<int:vale_id>/eliminar/", views_ti.vale_eliminar, name="vale_eliminar"),
    path("ti/vales/<int:vale_id>/restaurar/", views_ti.vale_restaurar, name="vale_restaurar"),
    path("ti/solicitudes/", views_ti.solicitudes_anulacion, name="solicitudes_anulacion"),
    path("ti/solicitudes/<int:solicitud_id>/resolver/", views_ti.solicitud_resolver, name="solicitud_resolver"),
    path("ti/bitacora/", views_ti.bitacora_list, name="bitacora"),
]
