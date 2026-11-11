from django.db import models
from app.cuentas.models import Perfil

class Bitacora(models.Model):
    perfil = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True)
    accion = models.CharField(max_length=255)
    detalle = models.TextField(blank=True, null=True)
    ip = models.CharField(max_length=50, blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["perfil", "-fecha"], name="bit_perfil_fecha"),
            models.Index(fields=["-fecha"], name="bit_fecha_idx"),
        ]

    def __str__(self):
        return f"{self.fecha} - {self.accion}"
