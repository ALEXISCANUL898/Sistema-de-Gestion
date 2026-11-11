from django.urls import path
from . import views

urlpatterns = [
    path('solicitud/', views.prestamo_solicitud, name='prestamo_solicitud'),
    path('comprobante/<str:folio>/', views.prestamo_comprobante, name='prestamo_comprobante'),
    path('admin-panel/', views.prestamo_admin_panel, name='prestamo_admin_panel'),
    path('cambiar-estado/<str:folio>/', views.prestamo_cambiar_estado, name='prestamo_cambiar_estado'),
    path('imprimir/<str:folio>/', views.prestamo_imprimir, name='prestamo_imprimir'),
]
