from django.urls import path
from . import views

app_name = "catalogos"

urlpatterns = [
    # Empresas
    path("empresas/", views.empresas, name="empresas"),
    path("empresas/<int:pk>/editar/", views.empresa_editar, name="empresa_editar"),
    path("empresas/<int:pk>/toggle/", views.empresa_toggle, name="empresa_toggle"),

    # Áreas
    path("areas/", views.areas, name="areas"),
    path("areas/<int:pk>/editar/", views.area_editar, name="area_editar"),
    path("areas/<int:pk>/toggle/", views.area_toggle, name="area_toggle"),

    # Planos / Proyectos
    path("planos/", views.planos, name="planos"),
    path("planos/<int:pk>/editar/", views.plano_editar, name="plano_editar"),
    path("planos/<int:pk>/toggle/", views.plano_toggle, name="plano_toggle"),

    # Unidades
    path("unidades/", views.unidades, name="unidades"),
    path("unidades/<int:pk>/editar/", views.unidad_editar, name="unidad_editar"),
    path("unidades/<int:pk>/toggle/", views.unidad_toggle, name="unidad_toggle"),

    # Materiales
    path("materiales/", views.materiales, name="materiales"),
    path("materiales/<int:pk>/editar/", views.material_editar, name="material_editar"),
    path("materiales/<int:pk>/toggle/", views.material_toggle, name="material_toggle"),
    path("materiales/buscar/", views.material_buscar, name="material_buscar"),

    # Configuración global
    path("configuracion/", views.configuracion, name="configuracion"),
]
