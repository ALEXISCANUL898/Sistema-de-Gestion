from django.db import models

class Reservacion(models.Model):
    SALA_CHOICES = [
        ('SALA_1', 'Sala de Juntas General'),
        ('SALA_2', 'Sala Comercial 1'),
        ('SALA_3', 'Sala Comercial 2'),
        ('SALA_4', 'Sala Común')
    ]

    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    departamento = models.CharField(max_length=100, verbose_name="Departamento")
    puesto = models.CharField(max_length=100, verbose_name="Puesto")
    sala = models.CharField(max_length=10, choices=SALA_CHOICES, verbose_name="Sala")
    fecha = models.DateField(verbose_name="Fecha")
    hora_inicio = models.TimeField(verbose_name="Hora Inicio")
    hora_fin = models.TimeField(verbose_name="Hora Fin")
    usuario = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Usuario Creador")
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} - {self.sala} - {self.fecha}"

    class Meta:
        verbose_name = "Reservación"
        verbose_name_plural = "Reservaciones"
        ordering = ['fecha', 'hora_inicio']
        indexes = [
            models.Index(fields=["fecha", "sala"], name="res_fecha_sala"),
            models.Index(fields=["usuario"], name="res_usuario_idx"),
        ]
