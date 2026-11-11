from django.contrib import admin
from .models import SolicitudPrestamo


@admin.register(SolicitudPrestamo)
class SolicitudPrestamoAdmin(admin.ModelAdmin):
    list_display = ('folio', 'nombre_completo', 'area_departamento', 'fecha_inicio_uso', 'fecha_devolucion', 'estado', 'creado_en')
    list_filter = ('estado', 'fecha_inicio_uso', 'area_departamento')
    search_fields = ('folio', 'nombre_completo', 'correo', 'area_departamento')
    readonly_fields = ('folio', 'creado_en', 'actualizado_en', 'fecha_hora_aceptacion')
    ordering = ('-creado_en',)
    list_editable = ('estado',)
