from django.shortcuts import redirect
from django.utils import timezone
from django.conf import settings
from app.cuentas.models import Perfil


class PerfilActivoMiddleware:
    """
    - Adjunta `request.perfil_activo` desde la sesión.
    - Revisa inactividad: si el perfil lleva más de INACTIVIDAD_TIMEOUT_MINUTOS
      sin actividad, lo desloguea del perfil (no de la cuenta) y redirige a
      la selección de perfil.
    - Renueva `ultima_actividad` en cada request.
    """

    URLS_EXENTAS = (
        "/cuentas/login/",
        "/cuentas/logout/",
        "/cuentas/perfil/",
        "/admin/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Adjuntar perfil activo a request
        request.perfil_activo = None
        perfil_id = request.session.get("perfil_id")
        if perfil_id:
            try:
                request.perfil_activo = Perfil.objects.get(pk=perfil_id, activo=True)
            except Perfil.DoesNotExist:
                # Perfil inactivo o eliminado: limpiar sesión
                request.session.pop("perfil_id", None)
                request.session.pop("ultima_actividad", None)

        # Verificar inactividad si hay perfil activo
        if request.perfil_activo and not self._es_url_exenta(request.path):
            timeout = getattr(settings, "INACTIVIDAD_TIMEOUT_MINUTOS", 5)
            ultima = request.session.get("ultima_actividad")
            if ultima:
                desde = timezone.now() - timezone.datetime.fromisoformat(ultima).replace(
                    tzinfo=timezone.get_current_timezone()
                )
                if desde.total_seconds() > timeout * 60:
                    request.session.pop("perfil_id", None)
                    request.session.pop("ultima_actividad", None)
                    request.perfil_activo = None
                    return redirect("cuentas:seleccionar_perfil")

            # Renovar timestamp de actividad
            request.session["ultima_actividad"] = timezone.now().isoformat()

        response = self.get_response(request)
        return response

    def _es_url_exenta(self, path):
        return any(path.startswith(u) for u in self.URLS_EXENTAS)
