from functools import wraps
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied


def login_perfil_requerido(view_func):
    """
    Exige que la cuenta esté autenticada Y que haya un perfil activo en sesión
    o que sea un usuario autenticado por la Central de Sistemas.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("intranet_home")
        # Si proviene de la autenticación central (Intranet API)
        if (
            request.session.get("access_token")
            or request.session.get("permiso_Catalogos")
            or request.session.get("permiso_Almacen")
            or request.session.get("permiso_Auditoria")
            or request.user.is_superuser
        ):
            return view_func(request, *args, **kwargs)
        if not request.session.get("perfil_id"):
            from django.contrib import messages as django_messages
            django_messages.warning(request, "Selecciona tu perfil para continuar.")
            return redirect("cuentas:seleccionar_perfil")
        return view_func(request, *args, **kwargs)
    return _wrapped


def nivel_requerido(nivel_min):
    """
    Exige que el perfil activo pertenezca a una cuenta con nivel >= nivel_min,
    o valida el nivel obtenido desde la API Central.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("intranet_home")

            # Superusuario o admin local siempre tiene acceso total
            if request.user.is_superuser or request.user.username == "admin":
                return view_func(request, *args, **kwargs)

            # Si proviene de la autenticación central (Intranet API)
            permiso_cat = request.session.get("permiso_Catalogos", {})
            permiso_alm = request.session.get("permiso_Almacen", {})
            permiso_aud = request.session.get("permiso_Auditoria", {})

            has_central_session = bool(
                request.session.get("access_token")
                or permiso_cat
                or permiso_alm
                or permiso_aud
            )

            if has_central_session:
                # Vistas de catálogos simples: accesibles con nivel >= 1 de Catálogos
                if request.path.startswith("/catalogos/"):
                    if int(permiso_cat.get("nivel_acceso", 0)) >= 1 or int(permiso_alm.get("nivel_acceso", 0)) >= 1:
                        return view_func(request, *args, **kwargs)

                # Vistas del Panel TI (Cuentas, perfiles, vales eliminados): exigen nivel_min
                nivel_usuario = max(
                    int(permiso_cat.get("nivel_acceso", 0)),
                    int(permiso_alm.get("nivel_acceso", 0)),
                    int(permiso_aud.get("nivel_acceso", 0)),
                )

                if nivel_usuario < nivel_min:
                    from django.contrib import messages
                    messages.error(
                        request,
                        f"Acceso denegado: El Panel TI requiere nivel {nivel_min}. Tu nivel actual es {nivel_usuario}."
                    )
                    if int(permiso_cat.get("nivel_acceso", 0)) > 0 or int(permiso_alm.get("nivel_acceso", 0)) > 0:
                        return redirect("catalogos:empresas")
                    return redirect("intranet_home")

                return view_func(request, *args, **kwargs)

            # Compatibilidad local heredada
            if not request.session.get("perfil_id"):
                return redirect("cuentas:seleccionar_perfil")
            try:
                nivel = request.user.extension.nivel
            except Exception:
                raise PermissionDenied
            if nivel < nivel_min:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def rol_almacen_requerido(*roles):
    """
    Exige que el perfil activo tenga un rol_almacen incluido en *roles.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("intranet_home")
            if (
                request.session.get("access_token")
                or request.session.get("permiso_Catalogos")
                or request.session.get("permiso_Almacen")
                or request.session.get("permiso_Auditoria")
                or request.user.is_superuser
            ):
                return view_func(request, *args, **kwargs)
            perfil = getattr(request, "perfil_activo", None)
            if perfil is None or perfil.rol_almacen not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def solo_lectura_nivel4(view_func):
    """
    Nivel 4 (Gerencia): solo lectura.
    Si el nivel es 4 y el request es POST/PUT/PATCH/DELETE → 403.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        try:
            nivel = request.user.extension.nivel
        except Exception:
            nivel = None
        if nivel == 4 and request.method not in ("GET", "HEAD", "OPTIONS"):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped
