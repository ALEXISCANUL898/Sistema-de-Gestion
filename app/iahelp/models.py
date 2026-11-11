from django.db import models
from django.contrib.auth.models import User


class Ticket(models.Model):
    """Ticket de soporte técnico."""

    LEVEL_CHOICES = [
        (1, "Nivel 1"),
        (2, "Nivel 2"),
        (3, "Nivel 3"),
        (4, "Nivel 4"),
    ]

    PRIORITY_CHOICES = [
        ("Crítica", "Crítica"),
        ("Urgente", "Urgente"),
        ("Alta", "Alta"),
        ("Media", "Media"),
        ("Baja", "Baja"),
    ]

    STATUS_CHOICES = [
        ("Abierto", "Abierto"),
        ("En Progreso", "En Progreso"),
        ("Cerrado", "Cerrado"),
    ]

    user = models.ForeignKey(User, db_column="user_id", on_delete=models.DO_NOTHING)
    title = models.CharField("Título", max_length=255)
    description = models.TextField("Descripción")
    category = models.CharField("Categoría", max_length=100, blank=True, null=True)
    nivel = models.IntegerField(
        "Nivel de Escalamiento", choices=LEVEL_CHOICES, default=1
    )
    nivel_usuario = models.IntegerField(
        "Nivel del Usuario", choices=LEVEL_CHOICES, default=1,
        help_text="Nivel máximo del usuario que creó el ticket"
    )
    priority = models.CharField(
        "Prioridad", max_length=10, choices=PRIORITY_CHOICES, default="Media"
    )
    status = models.CharField(
        "Estado", max_length=20, choices=STATUS_CHOICES, default="Abierto"
    )
    ai_summary = models.TextField("Resumen IA", blank=True, null=True)
    ai_suggested_response = models.TextField("Sugerencia IA", blank=True, null=True)
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)
    usuario = models.CharField("Usuario", max_length=150, blank=True, default="")
    email = models.EmailField("Correo del usuario", blank=True, null=True, help_text="Correo para notificaciones")

    class Meta:
        managed = True
        ordering = ["-created_at"]
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        indexes = [
            models.Index(fields=["user", "status", "-created_at"], name="tick_user_status_idx"),
            models.Index(fields=["status", "-created_at"], name="tick_status_idx"),
            models.Index(fields=["created_at"], name="tick_created_idx"),
        ]

    def save(self, *args, **kwargs):
        """
        Escalada automática de prioridad según nivel.
        Mapeo de niveles a prioridades:
        - Nivel 4 (Ejecutivo) → SIEMPRE Crítica
        - Nivel 3 (Especialista) → Urgente (escalada)
        - Nivel 2 (Técnico) → Alta
        - Nivel 1 (Usuario) → Media/Baja
        """
        if self.nivel == 4:
            # Nivel 4: SIEMPRE Crítica (incidencia máxima)
            self.priority = "Crítica"
        elif self.nivel == 3:
            # Nivel 3: Escalado a Urgente
            if self.priority in ("Baja", "Media"):
                self.priority = "Urgente"
        elif self.nivel == 2:
            # Nivel 2: Técnico - Alta prioridad
            if self.priority == "Baja":
                self.priority = "Alta"
        # Nivel 1: El usuario define la prioridad
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"#{self.id} - {self.title}"


class TicketMessage(models.Model):
    """Mensaje dentro de la conversación de un ticket."""

    SENDER_CHOICES = [
        ("user", "Usuario"),
        ("agent", "Agente de Soporte"),
        ("ai", "IA"),
        ("system", "Sistema"),
    ]

    ticket = models.ForeignKey(
        Ticket,
        db_column="ticket_id",
        on_delete=models.DO_NOTHING,
        related_name="messages",
    )
    sender = models.CharField("Remitente", max_length=20, choices=SENDER_CHOICES)
    message = models.TextField("Mensaje")
    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        managed = True
        ordering = ["created_at"]
        verbose_name = "Mensaje"
        verbose_name_plural = "Mensajes"
        indexes = [
            models.Index(fields=["ticket", "-created_at"], name="tmsg_tick_created_idx"),
            models.Index(fields=["ticket", "sender", "-created_at"], name="tmsg_tick_sender_idx"),
        ]

    def __str__(self):
        return f"[{self.sender}] {self.message[:50]}"


class AiLog(models.Model):
    """Registro de trazabilidad de llamadas a la IA (Soporta Ticket e EcontrolTicket)."""

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="ai_logs",
        null=True,
        blank=True,
    )
    econtrol_ticket = models.ForeignKey(
        'EcontrolTicket',
        on_delete=models.CASCADE,
        related_name="ai_logs",
        null=True,
        blank=True,
    )
    prompt = models.TextField("Prompt enviado", default="")
    ai_response = models.TextField("Respuesta recibida", default="")
    model_used = models.CharField("Modelo", max_length=100)
    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Log IA"
        verbose_name_plural = "Logs IA"

    def __str__(self):
        ticket_id = f"T#{self.ticket.id}" if self.ticket else (f"EC#{self.econtrol_ticket.id}" if self.econtrol_ticket else "N/A")
        return f"Log {ticket_id} - {self.model_used}"


class Sistema(models.Model):
    """Sistemas a los que se puede tener acceso."""

    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=50, unique=True)
    url = models.URLField(blank=True, null=True)

    class Meta:
        managed = True
        verbose_name = "Sistema"
        verbose_name_plural = "Sistemas"

    def __str__(self):
        return self.nombre


class Rol(models.Model):
    """Roles de usuario con nivel de acceso."""

    nombre = models.CharField(max_length=100)
    nivel_acceso = models.IntegerField(default=1)

    class Meta:
        managed = True
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        return f"{self.nombre} (Nivel {self.nivel_acceso})"


class UsuarioSistema(models.Model):
    """Relación entre usuarios, sistemas y roles."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="permisos_sistemas"
    )
    sistema = models.ForeignKey(
        Sistema, on_delete=models.CASCADE, related_name="usuarios"
    )
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE)

    class Meta:
        managed = True
        unique_together = ("user", "sistema")
        verbose_name = "Permiso de Sistema"
        verbose_name_plural = "Permisos de Sistemas"

    def __str__(self):
        return f"{self.user.username} - {self.sistema.codigo} ({self.rol.nombre})"


class EcontrolTicket(models.Model):
    """Tickets específicos del sistema Enkontrol."""

    PRIORITY_CHOICES = [
        ("Crítica", "Crítica"),
        ("Urgente", "Urgente"),
        ("Alta", "Alta"),
        ("Media", "Media"),
        ("Baja", "Baja"),
    ]

    STATUS_CHOICES = [
        ("Abierto", "Abierto"),
        ("En Progreso", "En Progreso"),
        ("Cerrado", "Cerrado"),
    ]

    user = models.ForeignKey(User, db_column="user_id", on_delete=models.DO_NOTHING)
    title = models.CharField("Título", max_length=255)
    description = models.TextField("Descripción")
    nivel = models.IntegerField("Nivel de Escalamiento", default=4)
    nivel_usuario = models.IntegerField("Nivel del Usuario", default=4)
    category = models.CharField("Categoría", max_length=100, blank=True, null=True)
    priority = models.CharField("Prioridad", max_length=10, choices=PRIORITY_CHOICES, default="Media")
    status = models.CharField("Estado", max_length=20, choices=STATUS_CHOICES, default="Abierto")
    ai_summary = models.TextField("Resumen IA", blank=True, null=True)
    ai_suggested_response = models.TextField("Sugerencia IA", blank=True, null=True)
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)
    usuario = models.CharField("Usuario", max_length=150, blank=True, default="")
    email = models.EmailField("Correo del usuario", blank=True, null=True)
    email_analista_erp = models.EmailField("Correo analista ERP", blank=True, null=True)

    class Meta:
        managed = True
        ordering = ["-created_at"]
        verbose_name = "Ticket Enkontrol"
        verbose_name_plural = "Tickets Enkontrol"
        indexes = [
            models.Index(fields=["user", "status", "-created_at"], name="ectl_user_status_idx"),
            models.Index(fields=["status", "-created_at"], name="ectl_status_idx"),
            models.Index(fields=["created_at"], name="ectl_created_idx"),
        ]

    def save(self, *args, **kwargs):
        # El nivel y prioridad se manejarán por defecto o por la lógica de creación
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ENKONTROL-#{self.id} - {self.title}"


class EcontrolTicketMessage(models.Model):
    """Mensaje dentro de la conversación de un ticket Enkontrol."""
    SENDER_CHOICES = [
        ("user", "Usuario"),
        ("agent", "Agente de Soporte"),
        ("ai", "IA"),
        ("system", "Sistema"),
    ]

    ticket = models.ForeignKey(
        EcontrolTicket,
        db_column="ticket_id",
        on_delete=models.DO_NOTHING,
        related_name="messages",
    )
    sender = models.CharField("Remitente", max_length=20, choices=SENDER_CHOICES)
    message = models.TextField("Mensaje")
    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        managed = True
        ordering = ["created_at"]
        verbose_name = "Mensaje Enkontrol"
        verbose_name_plural = "Mensajes Enkontrol"
        indexes = [
            models.Index(fields=["ticket", "-created_at"], name="ectlm_tick_created_idx"),
            models.Index(fields=["ticket", "sender", "-created_at"], name="ectlm_tick_sender_idx"),
        ]

    def __str__(self):
        return f"[{self.sender}] {self.message[:50]}"


class TrabajoFondo(models.Model):
    """Cola de trabajos en MySQL (etapa 4C, sin Redis/Celery).

    Tipos: ANALIZAR_TICKET, ANALIZAR_ECONTROL.
    El worker (cola_worker --once, tarea cada 2 min) los procesa con SKIP LOCKED.
    Si el worker muere, las vistas usan la vía sincrónica (cola_viva()).
    """
    TIPOS = (
        ("ANALIZAR_TICKET", "Analizar ticket IA Help"),
        ("ANALIZAR_ECONTROL", "Analizar ticket Enkontrol"),
    )
    ESTADOS = (
        ("PENDIENTE", "Pendiente"),
        ("PROCESANDO", "Procesando"),
        ("OK", "Terminado"),
        ("ERROR", "Error"),
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    ticket_id = models.IntegerField(help_text="ID del Ticket o EcontrolTicket")
    estado = models.CharField(max_length=12, choices=ESTADOS, default="PENDIENTE")
    intentos = models.IntegerField(default=0)
    max_intentos = models.IntegerField(default=3)
    programado_para = models.DateTimeField(help_text="No procesar antes de esta hora (backoff)")
    payload = models.JSONField(default=dict, blank=True)
    resultado = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "Trabajo en fondo"
        verbose_name_plural = "Trabajos en fondo"
        indexes = [
            models.Index(fields=["estado", "programado_para"], name="trab_est_prog"),
            models.Index(fields=["tipo", "ticket_id", "-creado"], name="trab_tipo_tick"),
        ]

    def __str__(self):
        return f"{self.tipo} #{self.ticket_id} [{self.estado}]"


class LatidoWorker(models.Model):
    """Heartbeat del worker de cola (una fila por worker)."""
    nombre = models.CharField(max_length=50, unique=True)
    ultimo = models.DateTimeField()

    def __str__(self):
        return f"{self.nombre}: {self.ultimo}"
