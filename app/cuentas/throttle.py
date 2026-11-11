"""Throttle de intentos de login web (contraseña) con caché local.

Sin dependencias nuevas. Clave por (IP, usuario): 5 fallos → bloqueo 15 min.
No toca el flujo feliz; solo frena fuerza bruta contra login web y central.
"""
from django.core.cache import cache
from django.conf import settings

MAX_INTENTOS = int(getattr(settings, "LOGIN_MAX_INTENTOS", 5))
BLOQUEO_MIN = int(getattr(settings, "LOGIN_BLOQUEO_MINUTOS", 15))


def _key(ip, username):
    return f"loginfail:{(ip or '').strip()}:{str(username or '').strip().lower()}"


def ip_de(request):
    try:
        return request.META.get("REMOTE_ADDR", "")
    except Exception:
        return ""


def intentos(ip, username):
    try:
        return int(cache.get(_key(ip, username)) or 0)
    except Exception:
        return 0


def bloqueado(ip, username):
    return intentos(ip, username) >= MAX_INTENTOS


def registrar_fallo(ip, username):
    """Suma un fallo; devuelve intentos restantes antes del bloqueo."""
    k = _key(ip, username)
    try:
        n = int(cache.get(k) or 0) + 1
        cache.set(k, n, BLOQUEO_MIN * 60)
    except Exception:
        n = MAX_INTENTOS
    return max(0, MAX_INTENTOS - n)


def limpiar(ip, username):
    try:
        cache.delete(_key(ip, username))
    except Exception:
        pass


def mensaje_bloqueo():
    return (f"Demasiados intentos fallidos. "
            f"Tu acceso está bloqueado por {BLOQUEO_MIN} minutos.")
