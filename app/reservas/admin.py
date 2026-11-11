from django.contrib import admin
from .models import Reservacion

@admin.register(Reservacion)
class ReservacionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'sala', 'fecha', 'hora_inicio', 'hora_fin', 'departamento')
    list_filter = ('sala', 'fecha', 'departamento')
    search_fields = ('nombre', 'departamento', 'puesto')
