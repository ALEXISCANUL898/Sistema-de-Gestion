"""Validadores de imagen compartidos (nivel formulario, sin migración)."""
from django.core.exceptions import ValidationError

MAX_IMAGEN_BYTES = 2 * 1024 * 1024
TIPOS_PERMITIDOS = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def validar_imagen(upload):
    """Rechaza archivos no-imagen, >2MB o corruptos. No rompe si falta archivo."""
    if not upload:
        return upload
    ctype = getattr(upload, "content_type", "") or ""
    if ctype and ctype not in TIPOS_PERMITIDOS:
        raise ValidationError("Solo se permiten imágenes JPG, PNG, GIF o WEBP.")
    try:
        size = upload.size
    except Exception:
        size = 0
    if size and size > MAX_IMAGEN_BYTES:
        raise ValidationError("La imagen supera 2 MB.")
    try:
        from PIL import Image
        upload.seek(0)
        im = Image.open(upload)
        im.verify()
        upload.seek(0)
    except Exception:
        raise ValidationError("Archivo de imagen inválido.")
    return upload
