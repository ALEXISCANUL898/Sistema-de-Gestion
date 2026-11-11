from django.db import models
from django.utils import timezone
from app.cuentas.models import Perfil
from app.catalogos.models import Empresa, Area, Plano, Material, Unidad

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(eliminado=False)

class Vale(models.Model):
    ESTADOS = (
        ('BORRADOR', 'Borrador'),
        ('EMITIDO', 'Emitido'),
        ('ASIGNADO', 'Asignado'),
        ('PARCIAL', 'Parcial'),
        ('POR_CERRAR', 'Por cerrar'),
        ('CERRADO', 'Cerrado'),
        ('CERRADO_CON_FALTANTE', 'Cerrado con faltante'),
        ('PRESTAMO_ABIERTO', 'Préstamo abierto'),
        ('ANULADO', 'Anulado'),
    )
    TIPOS_MOVIMIENTO = (
        ('Salida de material', 'Salida de material'),
        ('Devolución', 'Devolución'),
        ('Préstamo', 'Préstamo'),
        ('Otro', 'Otro'),
    )
    tipo_movimiento = models.CharField(max_length=50, choices=TIPOS_MOVIMIENTO, default='Salida de material')
    tipo_detalle = models.CharField(max_length=100, blank=True, help_text="Especifique (solo si tipo es Otro)")
    # El consecutivo se asigna al EMITIR, nunca en borrador; un número anulado jamás se reutiliza.
    consecutivo = models.CharField(max_length=20, unique=True, editable=False, null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)
    creado_por = models.ForeignKey(Perfil, on_delete=models.PROTECT, related_name='vales_creados')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='BORRADOR')
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, null=True, blank=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, null=True, blank=True)
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT, null=True, blank=True)
    dato_otro = models.CharField(max_length=255, blank=True, help_text="Campo libre (Empresa/Área/Plano/Otro)")
    notas = models.TextField(blank=True)
    motivo_cierre = models.TextField(blank=True, help_text="Motivo del cierre con faltante (solo encargado)")
    eliminado = models.BooleanField(default=False)
    eliminado_por = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True, related_name='vales_eliminados')
    motivo_eliminacion = models.TextField(blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()  # includes deleted

    class Meta:
        indexes = [
            models.Index(fields=["eliminado", "estado", "-fecha"], name="vale_elim_est_fecha"),
            models.Index(fields=["eliminado", "-fecha"], name="vale_elim_fecha_idx"),
            models.Index(fields=["creado_por", "eliminado"], name="vale_creador_elim"),
        ]

    def asignar_consecutivo(self):
        """Asigna el siguiente N° consecutivo con bloqueo transaccional.
        Debe llamarse al EMITIR, dentro de una transacción atómica."""
        from django.db import transaction
        from app.catalogos.models import Configuracion
        with transaction.atomic():
            cfg, _ = Configuracion.objects.select_for_update().get_or_create(pk=1)
            cfg.ultimo_consecutivo = (cfg.ultimo_consecutivo or 0) + 1
            cfg.save(update_fields=["ultimo_consecutivo"])
            self.consecutivo = f"{cfg.ultimo_consecutivo:06d}"

    def soft_delete(self, perfil, motivo):
        self.eliminado = True
        self.eliminado_por = perfil
        self.motivo_eliminacion = motivo
        self.save()

    def __str__(self):
        return f"Vale {self.consecutivo} - {self.estado}" 

class DetalleVale(models.Model):
    vale = models.ForeignKey(Vale, on_delete=models.CASCADE, related_name='detalles')
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    cantidad_solicitada = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad_entregada = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unidad = models.ForeignKey(Unidad, on_delete=models.PROTECT)
    ESTADO_LINEA = (
        ('PENDIENTE', 'Pendiente'),
        ('PARCIAL', 'Parcial'),
        ('COMPLETA', 'Completa'),
        ('SIN_EXISTENCIA', 'Sin existencia'),
    )
    estado_linea = models.CharField(max_length=20, choices=ESTADO_LINEA, default='PENDIENTE')

    def actualizar_estado(self):
        if self.cantidad_entregada == 0:
            self.estado_linea = 'PENDIENTE'
        elif self.cantidad_entregada < self.cantidad_solicitada:
            self.estado_linea = 'PARCIAL'
        else:
            # >= solicitada (incluye sobre-entrega autorizada)
            self.estado_linea = 'COMPLETA'
        self.save()

    def __str__(self):
        return f"{self.material.descripcion} - {self.cantidad_solicitada}{self.unidad.abreviatura}" 

class AsignacionVale(models.Model):
    vale = models.ForeignKey(Vale, on_delete=models.CASCADE, related_name='asignaciones')
    asignado_a = models.ForeignKey(Perfil, on_delete=models.PROTECT, limit_choices_to={'rol_almacen': 'DESPACHADOR'})
    asignado_por = models.ForeignKey(Perfil, on_delete=models.PROTECT, related_name='asignaciones_realizadas')
    fecha = models.DateTimeField(default=timezone.now)
    vigente = models.BooleanField(default=True)
    motivo_reasignacion = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["vale", "vigente"], name="asig_vale_vigente"),
            models.Index(fields=["asignado_a", "vigente"], name="asig_dest_vigente"),
        ]

    def __str__(self):
        return f"{self.vale.consecutivo} -> {self.asignado_a.nombre}" 

class FirmaSnapshot(models.Model):
    TIPO = (
        ('RETIRADO', 'Retirado'),
        ('ENTREGA', 'Entrega'),
        ('DESPACHADO', 'Despachado'),
        ('EXCEPCION', 'Excepción'),
        ('ELIMINACION', 'Eliminación'),
    )
    vale = models.ForeignKey(Vale, on_delete=models.CASCADE, related_name='firmas')
    tipo = models.CharField(max_length=20, choices=TIPO)
    nombre = models.CharField(max_length=255)
    puesto = models.CharField(max_length=255)
    firma = models.ImageField(upload_to='firmas_vales/')
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} - {self.nombre}" 

class Entrega(models.Model):
    ESTADOS = (
        ('ACTIVA', 'Activa'),
        ('ANULADA', 'Anulada'),
    )
    vale = models.ForeignKey(Vale, on_delete=models.CASCADE, related_name='entregas')
    perfil = models.ForeignKey(Perfil, on_delete=models.PROTECT, related_name='entregas',
                               help_text="Quien registra la entrega en el sistema (encargado)")
    entregado_por = models.ForeignKey(Perfil, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name='entregas_fisicas',
                                      help_text="Quien entregó en físico (despachador asignado)")
    fecha = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=10, choices=ESTADOS, default='ACTIVA')
    motivo_anulacion = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["vale", "estado"], name="entr_vale_estado"),
        ]

    def __str__(self):
        return f"Entrega {self.id} - Vale {self.vale.consecutivo}" 

class DetalleEntrega(models.Model):
    entrega = models.ForeignKey(Entrega, on_delete=models.CASCADE, related_name='detalles')
    detalle_vale = models.ForeignKey(DetalleVale, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    observaciones = models.CharField(max_length=255, blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # actualizar cantidades en DetalleVale (F() evita lost-update concurrente)
        from django.db.models import F
        DetalleVale.objects.filter(pk=self.detalle_vale_id).update(
            cantidad_entregada=F('cantidad_entregada') + self.cantidad)
        dv = DetalleVale.objects.get(pk=self.detalle_vale_id)
        dv.actualizar_estado()
        dv.save()

    def __str__(self):
        return f"{self.detalle_vale.material.descripcion}: {self.cantidad}" 

class SolicitudAnulacion(models.Model):
    vale = models.ForeignKey(Vale, on_delete=models.CASCADE, related_name='solicitudes_anulacion')
    solicitante = models.ForeignKey(Perfil, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)
    aprovada = models.BooleanField(null=True)  # None = pending
    aprobado_por = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True, related_name='anulaciones_aprobadas')
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["aprovada"], name="solan_aprobada_idx"),
        ]

    def __str__(self):
        return f"Solicitud Anulacion Vale {self.vale.consecutivo}" 

