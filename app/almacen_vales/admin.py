from django.contrib import admin
from .models import (
    Vale, DetalleVale, AsignacionVale,
    FirmaSnapshot, Entrega,
    SolicitudAnulacion,
)


class DetalleValeInline(admin.TabularInline):
    model = DetalleVale
    extra = 1
    readonly_fields = ("cantidad_entregada", "estado_linea")


class FirmaSnapshotInline(admin.TabularInline):
    model = FirmaSnapshot
    extra = 0
    readonly_fields = ("tipo", "nombre", "puesto", "firma", "fecha")
    can_delete = False


class EntregaInline(admin.TabularInline):
    model = Entrega
    extra = 0
    readonly_fields = ("perfil", "fecha", "estado")
    can_delete = False


@admin.register(Vale)
class ValeAdmin(admin.ModelAdmin):
    list_display = ("consecutivo", "tipo_movimiento", "estado", "creado_por", "empresa", "fecha")
    list_filter = ("estado", "tipo_movimiento", "empresa")
    search_fields = ("consecutivo", "creado_por__nombre")
    date_hierarchy = "fecha"
    readonly_fields = ("consecutivo", "eliminado_por", "motivo_eliminacion")
    inlines = [DetalleValeInline, FirmaSnapshotInline, EntregaInline]

    def get_queryset(self, request):
        # Admin shows all, including deleted
        return Vale.all_objects.all()


@admin.register(AsignacionVale)
class AsignacionValeAdmin(admin.ModelAdmin):
    list_display = ("vale", "asignado_a", "asignado_por", "vigente", "fecha")
    list_filter = ("vigente",)
    search_fields = ("vale__consecutivo", "asignado_a__nombre")


@admin.register(Entrega)
class EntregaAdmin(admin.ModelAdmin):
    list_display = ("vale", "perfil", "fecha", "estado")
    list_filter = ("estado",)
    search_fields = ("vale__consecutivo",)
    readonly_fields = ("vale", "perfil", "fecha")


@admin.register(SolicitudAnulacion)
class SolicitudAnulacionAdmin(admin.ModelAdmin):
    list_display = ("vale", "solicitante", "fecha", "aprovada")
    list_filter = ("aprovada",)
    search_fields = ("vale__consecutivo",)

