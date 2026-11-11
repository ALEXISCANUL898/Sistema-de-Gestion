from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password

# PIN de 4 dígitos (se conserva por operativa). Lista negra mínima exigida:
# 0000, 1234 + 2 adicionales considerados de alto riesgo: 1111, 7777.
# Los formularios amplían con secuencias/repeticiones; aquí solo el mínimo.
PIN_DENEGADOS = frozenset({"0000", "1234", "1111", "7777"})


def es_pin_permitido(raw_pin):
    """True si el PIN tiene 4 dígitos y no está en lista negra."""
    p = str(raw_pin or "").strip()
    return p.isdigit() and len(p) == 4 and p not in PIN_DENEGADOS

class CuentaExtension(models.Model):
    NIVELES = (
        (1, 'Solicitante (Obra)'),
        (3, 'Almacén'),
        (4, 'Gerencia'),
        (6, 'Administrador TI'),
    )
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='extension')
    nivel = models.IntegerField(choices=NIVELES, default=1)

    def __str__(self):
        return f"{self.usuario.username} - Nivel {self.nivel}"

class Perfil(models.Model):
    ROLES_ALMACEN = (
        ('ENCARGADO', 'Encargado'),
        ('DESPACHADOR', 'Despachador'),
    )
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='perfiles')
    nombre = models.CharField(max_length=255)
    puesto = models.CharField(max_length=255)
    firma = models.ImageField(upload_to='firmas_perfiles/', null=True, blank=True)
    pin_hash = models.CharField(max_length=128)
    intentos_fallidos = models.IntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=True)
    rol_almacen = models.CharField(max_length=20, choices=ROLES_ALMACEN, null=True, blank=True)
    # ID de la identidad en el Control de Usuario central (si el perfil se espejó de ahí)
    central_id = models.IntegerField(null=True, blank=True, help_text="ID de IdentidadPerfil en la API Central")
    firma_central = models.CharField(max_length=255, blank=True, default="",
                                     help_text="Ruta de la firma en el central la última vez que se sincronizó")

    def set_pin(self, raw_pin):
        from django.core.exceptions import ValidationError
        if not es_pin_permitido(raw_pin):
            raise ValidationError("Este PIN no está permitido. Elige uno más seguro.")
        self.pin_hash = make_password(raw_pin)
        self.save()

    def check_pin(self, raw_pin):
        return check_password(raw_pin, self.pin_hash)

    def is_locked(self):
        if self.bloqueado_hasta and self.bloqueado_hasta > timezone.now():
            return True
        return False

    class Meta:
        indexes = [
            models.Index(fields=["usuario", "activo"], name="perf_usu_activo"),
            models.Index(fields=["central_id"], name="perf_central_idx"),
            models.Index(fields=["rol_almacen", "activo"], name="perf_rol_activo"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.puesto})"

