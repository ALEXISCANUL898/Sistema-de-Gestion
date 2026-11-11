from django.urls import path
from . import views

urlpatterns = [
    path('', views.reserva_list, name='reserva_list'),
    path('nueva/', views.reserva_create, name='reserva_create'),
    path('historial/', views.reserva_history, name='reserva_history'),
    path('cancelar/<int:pk>/', views.reserva_delete, name='reserva_delete'),
]
