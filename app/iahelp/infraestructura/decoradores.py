from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

def permission_level_required(min_level, system="iahelp", redirect_to="intranet_home"):
    """
    Decorador para verificar que el usuario tenga un nivel de acceso mínimo en un sistema específico.
    Si no cumple, redirige con un mensaje de error.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            session_key = f"permiso_{system}"
            permiso = request.session.get(session_key)
            
            # El administrador real (admin) siempre tiene acceso nivel 5
            is_real_admin = request.user.is_superuser and request.user.username == "admin"
            
            if is_real_admin:
                return view_func(request, *args, **kwargs)
                
            if not permiso:
                logger.warning(f"Intento de acceso sin sesión de permiso: {request.user.username} para {system}")
                messages.error(request, f"Debe iniciar sesión en el sistema {system} para continuar.")
                return redirect(redirect_to)
                
            nivel_acceso = int(permiso.get("nivel_acceso", 0))
            
            if nivel_acceso < min_level:
                logger.warning(f"Nivel insuficiente: {request.user.username} (Nivel {nivel_acceso}) intentó acceder a recurso Nivel {min_level} en {system}")
                messages.error(request, "No tiene los permisos suficientes para acceder a esta sección.")
                
                # Redirección inteligente basada en el nivel
                if system == "iahelp":
                    if nivel_acceso >= 1:
                        return redirect("iahelp")
                    return redirect("login")
                elif system == "enkontrol":
                    if nivel_acceso >= 1:
                        return redirect("econtrol_dashboard")
                    return redirect("econtrol_login")
                    
                return redirect(redirect_to)
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
