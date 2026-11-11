from django.db import models
from django.core.validators import MinValueValidator


class Empresa(models.Model):
    nombre = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Area(models.Model):
    nombre = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Plano(models.Model):
    nombre = models.CharField(max_length=255)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Plano / Proyecto"
        verbose_name_plural = "Planos / Proyectos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Unidad(models.Model):
    nombre = models.CharField(max_length=50)
    abreviatura = models.CharField(max_length=10, blank=True, null=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Unidad de medida"
        verbose_name_plural = "Unidades de medida"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Material(models.Model):
    folio = models.CharField(max_length=20, unique=True, blank=True, editable=False,
                             verbose_name="Folio",
                             help_text="Se genera automáticamente (MAT-XXXX).")
    descripcion = models.CharField(max_length=255)
    unidad_sugerida = models.ForeignKey(Unidad, on_delete=models.SET_NULL, null=True, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Material"
        verbose_name_plural = "Materiales"
        ordering = ["folio", "descripcion"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            base = f"MAT-{self.pk:04d}"
            folio, i = base, 0
            while Material.objects.filter(folio=folio).exclude(pk=self.pk).exists():
                i += 1
                folio = f"{base}-{i}"
            self.folio = folio
            super().save(update_fields=["folio"])

    def __str__(self):
        return f"{self.folio} — {self.descripcion}" if self.folio else self.descripcion


class Configuracion(models.Model):
    """Singleton de configuración global del sistema de vales."""
    logo = models.ImageField(
        upload_to="config/",
        null=True,
        blank=True,
        verbose_name="Logo de la empresa",
        help_text="Imagen que aparecerá en el encabezado de los vales (PNG/JPG).",
    )
    max_filas_vale = models.PositiveSmallIntegerField(
        default=12,
        validators=[MinValueValidator(1)],
        verbose_name="Máx. filas por vale",
        help_text="Número máximo de materiales permitidos en un solo vale.",
    )
    semaforo_amarillo_horas = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1)],
        verbose_name="Semáforo amarillo (horas)",
        help_text="Horas sin atención a partir de las cuales el vale cambia a amarillo.",
    )
    semaforo_rojo_horas = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1)],
        verbose_name="Semáforo rojo (horas)",
        help_text="Horas sin atención a partir de las cuales el vale cambia a rojo.",
    )
    inactividad_timeout_min = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        verbose_name="Tiempo de inactividad (minutos)",
        help_text="Minutos sin actividad antes de desloguear el perfil y regresar a la selección.",
    )
    ultimo_consecutivo = models.PositiveIntegerField(
        default=0,
        verbose_name="Último consecutivo asignado",
        help_text="Contador interno del N° de vale. Se incrementa con bloqueo al emitir.",
    )

    class Meta:
        verbose_name = "Configuración global"
        verbose_name_plural = "Configuración global"

    def save(self, *args, **kwargs):
        # Garantiza que sólo exista un registro (singleton)
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # No se puede eliminar el singleton
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Configuración global"
