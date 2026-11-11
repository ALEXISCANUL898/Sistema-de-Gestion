from django.contrib import admin
from .models import CuentaExtension, Perfil


@admin.register(CuentaExtension)
class CuentaExtensionAdmin(admin.ModelAdmin):
    list_display = ("usuario", "nivel")
    list_filter = ("nivel",)
    search_fields = ("usuario__username",)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("nombre", "puesto", "usuario", "rol_almacen", "activo")
    list_filter = ("rol_almacen", "activo")
    search_fields = ("nombre", "puesto", "usuario__username")
    readonly_fields = ("pin_hash", "intentos_fallidos", "bloqueado_hasta")
