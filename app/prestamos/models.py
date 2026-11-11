from django.db import models
import uuid


def generar_folio():
    """Genera un folio único para cada solicitud."""
    prefix = "PREST"
    uid = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{uid}"


class SolicitudPrestamo(models.Model):
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('aprobada', 'Aprobada'),
        ('devuelto', 'Devuelto'),
        ('rechazada', 'Rechazada'),
    ]

    # Folio único
    folio = models.CharField(max_length=20, unique=True, editable=False, verbose_name="Folio")

    # 1. Datos del solicitante
    nombre_completo = models.CharField(max_length=150, verbose_name="Nombre Completo")
    area_departamento = models.CharField(max_length=100, verbose_name="Área / Departamento")
    puesto = models.CharField(max_length=100, verbose_name="Puesto")
    correo = models.EmailField(verbose_name="Correo Electrónico")
    telefono = models.CharField(max_length=20, verbose_name="Teléfono")

    # 2. Datos de la solicitud
    fecha_inicio_uso = models.DateField(verbose_name="Fecha de Inicio de Uso")
    fecha_devolucion = models.DateField(verbose_name="Fecha de Devolución")
    hora_devolucion = models.TimeField(verbose_name="Hora Estimada de Devolución")
    contratista = models.CharField(max_length=150, default="N/A", verbose_name="Contratista")
    motivo_uso = models.TextField(verbose_name="Motivo de Uso")

    # 2.1 Datos del Equipo
    equipo = models.CharField(max_length=100, default="Generador Eléctrico", verbose_name="Equipo")
    marca = models.CharField(max_length=50, default="FUNDEER", verbose_name="Marca")
    modelo_equipo = models.CharField(max_length=50, default="Rg009Li", verbose_name="Modelo")
    potencia_nominal = models.CharField(max_length=50, default="300W", verbose_name="Potencia Nominal")
    tipo_bateria = models.CharField(max_length=50, default="LiFePO4", verbose_name="Tipo de Batería")

    # 3. Cláusula de responsabilidad
    acepto_terminos = models.BooleanField(default=False, verbose_name="Acepta Términos de Responsabilidad")
    fecha_hora_aceptacion = models.DateTimeField(null=True, blank=True, verbose_name="Fecha y Hora de Aceptación")

    # Estado de la solicitud
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='pendiente', verbose_name="Estado")

    # Metadatos
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Creado en")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Actualizado en")
    usuario = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Usuario del sistema"
    )

    def save(self, *args, **kwargs):
        if not self.folio:
            # Asegurar folio único
            folio = generar_folio()
            while SolicitudPrestamo.objects.filter(folio=folio).exists():
                folio = generar_folio()
            self.folio = folio
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.folio} - {self.nombre_completo} ({self.get_estado_display()})"

    class Meta:
        verbose_name = "Solicitud de Préstamo"
        verbose_name_plural = "Solicitudes de Préstamo"
        ordering = ['-creado_en']
        indexes = [
            models.Index(fields=["estado", "-creado_en"], name="prest_est_creado"),
        ]
