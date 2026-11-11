from django.contrib import admin
from django.utils import timezone
from .models import Ticket, TicketMessage, AiLog, TrabajoFondo, LatidoWorker


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "category", "nivel", "priority", "status", "created_at")
    list_filter = ("nivel", "priority", "status", "category")
    search_fields = ("title", "description")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Información del Ticket", {
            "fields": ("user", "title", "description", "category", "usuario")
        }),
        ("Escalamiento", {
            "fields": ("nivel", "priority"),
            "description": "Los tickets de Nivel 4 (Ejecutivo) tendrán automáticamente Prioridad Urgente"
        }),
        ("Estado", {
            "fields": ("status",)
        }),
        ("IA", {
            "fields": ("ai_summary", "ai_suggested_response"),
            "classes": ("collapse",)
        }),
        ("Auditoría", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "sender", "created_at")
    list_filter = ("sender",)
    search_fields = ("message",)
    readonly_fields = ("created_at",)


@admin.register(AiLog)
class AiLogAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "model_used", "created_at")
    list_filter = ("model_used",)
    readonly_fields = ("created_at",)


@admin.register(TrabajoFondo)
class TrabajoFondoAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "ticket_id", "estado", "intentos", "programado_para", "creado")
    list_filter = ("tipo", "estado")
    search_fields = ("ticket_id", "resultado", "error")
    readonly_fields = ("creado", "actualizado")
    actions = ("reintentar",)

    @admin.action(description="Reintentar trabajos seleccionados")
    def reintentar(self, request, queryset):
        n = queryset.filter(estado__in=("ERROR", "PROCESANDO")).update(
            estado="PENDIENTE", intentos=0, error="",
            programado_para=timezone.now())
        self.message_user(request, f"{n} trabajo(s) reencolados.")


@admin.register(LatidoWorker)
class LatidoWorkerAdmin(admin.ModelAdmin):
    list_display = ("nombre", "ultimo")
    readonly_fields = ("nombre", "ultimo")

    def has_add_permission(self, request):
        return False
