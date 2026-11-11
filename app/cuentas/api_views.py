"""API de validación de PIN de perfiles (identidades).

Endpoint: POST /api/permisos/verificar-pin/
Usado por la pantalla de selección de perfil para validar el PIN
sin exponer el hash y con bloqueo temporal + bitácora.
"""
import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from app.auditoria.models import Bitacora
from app.cuentas.models import Perfil

logger = logging.getLogger(__name__)

MAX_INTENTOS = getattr(settings, "PIN_MAX_INTENTOS", 5)
BLOQUEO_MINUTOS = getattr(settings, "PIN_BLOQUEO_MINUTOS", 15)


def _bitacora(perfil, accion, detalle="", request=None):
    ip = request.META.get("REMOTE_ADDR", "") if request else ""
    try:
        Bitacora.objects.create(perfil=perfil, accion=accion, detalle=detalle, ip=ip)
    except Exception as exc:  # la auditoría nunca debe romper el login
        logger.error("BITACORA ERROR: %s", exc)


class VerificarPinView(APIView):
    """Valida el PIN de una identidad (Perfil).

    Request JSON:
        { "identidad_id": 1, "pin": "1234" }
    Se acepta también "perfil_id" o "id" como alias de "identidad_id"
    por compatibilidad con el cliente actual.

    Response OK (200):
        { "status": "OK", "ok": true, "firma_url": "/media/..." }

    Errores:
        400 PIN con formato inválido / payload incompleto
        401 PIN incorrecto (+ intentos_restantes)
        403 Perfil inactivo o de otro usuario
        404 Perfil no encontrado
        423 Perfil bloqueado temporalmente
    """

    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        identidad_id = (
            data.get("identidad_id")
            or data.get("perfil_id")
            or data.get("id")
        )
        raw_pin = str(data.get("pin", "") or "").strip()

        if not identidad_id:
            return Response(
                {"status": "ERROR", "ok": False, "error": "Falta 'identidad_id'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not raw_pin.isdigit() or len(raw_pin) != 4:
            return Response(
                {"status": "ERROR", "ok": False, "error": "El PIN debe ser de 4 dígitos numéricos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            perfil = Perfil.objects.select_related("usuario").get(pk=identidad_id)
        except (Perfil.DoesNotExist, ValueError):
            return Response(
                {"status": "ERROR", "ok": False, "error": "Perfil no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not perfil.activo:
            return Response(
                {"status": "ERROR", "ok": False, "error": "Perfil desactivado. Contacta al administrador."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Seguridad: un usuario solo valida sus propios perfiles (salvo staff/superuser).
        if (
            perfil.usuario_id != request.user.id
            and not request.user.is_staff
            and not request.user.is_superuser
        ):
            _bitacora(perfil, "PIN_INTENTO_AJENO",
                       f"Usuario {request.user.username} intentó validar PIN ajeno.",
                       request)
            return Response(
                {"status": "ERROR", "ok": False, "error": "Sin permiso para este perfil."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if perfil.is_locked():
            return Response(
                {"status": "ERROR", "ok": False, "error": "Perfil bloqueado. Intenta más tarde."},
                status=status.HTTP_423_LOCKED,
            )

        if perfil.check_pin(raw_pin):
            update = ["intentos_fallidos"]
            perfil.intentos_fallidos = 0
            if perfil.bloqueado_hasta is not None:
                perfil.bloqueado_hasta = None
                update.append("bloqueado_hasta")
            perfil.save(update_fields=update)
            _bitacora(perfil, "PIN_OK",
                       f"PIN verificado para {perfil.nombre}.", request)
            firma_url = ""
            try:
                if perfil.firma and hasattr(perfil.firma, "url"):
                    firma_url = perfil.firma.url
            except Exception:
                firma_url = ""
            return Response(
                {
                    "status": "OK",
                    "ok": True,
                    "firma_url": firma_url,
                    "perfil": {"id": perfil.pk, "nombre": perfil.nombre},
                },
                status=status.HTTP_200_OK,
            )

        # PIN incorrecto
        perfil.intentos_fallidos = (perfil.intentos_fallidos or 0) + 1
        if perfil.intentos_fallidos >= MAX_INTENTOS:
            perfil.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=BLOQUEO_MINUTOS)
            perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
            _bitacora(perfil, "PERFIL_BLOQUEADO",
                       f"{perfil.intentos_fallidos} intentos fallidos de PIN.", request)
            return Response(
                {"status": "ERROR", "ok": False,
                 "error": "Perfil bloqueado por intentos fallidos."},
                status=status.HTTP_423_LOCKED,
            )
        perfil.save(update_fields=["intentos_fallidos"])
        restantes = MAX_INTENTOS - perfil.intentos_fallidos
        return Response(
            {"status": "ERROR", "ok": False,
             "error": f"PIN incorrecto. Intentos restantes: {restantes}.",
             "intentos_restantes": restantes},
            status=status.HTTP_401_UNAUTHORIZED,
        )
