from django.contrib import admin
from .models import Bitacora


@admin.register(Bitacora)
class BitacoraAdmin(admin.ModelAdmin):
    list_display = ("fecha", "accion", "perfil", "ip")
    list_filter = ("accion",)
    date_hierarchy = "fecha"
    search_fields = ("accion", "detalle", "perfil__nombre")
    readonly_fields = ("perfil", "accion", "detalle", "ip", "fecha")

    def has_add_permission(self, request):
        return False  # La bitácora es inmutable; nadie agrega registros manualmente

    def has_change_permission(self, request, obj=None):
        return False  # No se edita

    def has_delete_permission(self, request, obj=None):
        return False  # No se elimina

