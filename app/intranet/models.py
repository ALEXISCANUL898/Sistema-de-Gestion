from django.db import models

class Publication(models.Model):
    title = models.CharField(max_length=255, verbose_name="Título")
    description = models.TextField(verbose_name="Descripción")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha")
    image = models.ImageField(upload_to="intranet/publications/", null=True, blank=True, verbose_name="Imagen")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Publicación"
        verbose_name_plural = "Publicaciones"
        indexes = [
            models.Index(fields=["-created_at"], name="pub_created_idx"),
        ]

    def __str__(self):
        return self.title
