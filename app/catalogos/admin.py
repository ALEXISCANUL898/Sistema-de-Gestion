from django.contrib import admin
from .models import Empresa, Area, Plano, Unidad, Material


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Plano)
class PlanoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Unidad)
class UnidadAdmin(admin.ModelAdmin):
    list_display = ("nombre", "abreviatura", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("descripcion", "unidad_sugerida", "activa")
    list_filter = ("activa",)
    search_fields = ("descripcion",)

