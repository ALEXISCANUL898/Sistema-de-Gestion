from .base import *
import os
from dotenv import load_dotenv
import pymysql
pymysql.install_as_MySQLdb()

load_dotenv()


DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

# Hosts base (red local / localhost)
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "192.168.153.62",
    "192.168.150.200",
    "192.168.1.103",
    # Túneles de Cloudflare (quick tunnel cambia en cada ejecución,
    # el '.' inicial funciona como comodín: .trycloudflare.com = *.trycloudflare.com)
    ".trycloudflare.com",
    ".cfargotunnel.com",
]

# Permite añadir hosts extra sin tocar código:
# En .env -> ALLOWED_HOSTS_EXTRA=migration-stones-environmental-often.trycloudflare.com,midominio.com
_extra_hosts = os.environ.get("ALLOWED_HOSTS_EXTRA", "")
if _extra_hosts:
    ALLOWED_HOSTS += [h.strip() for h in _extra_hosts.split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = [
    "http://192.168.150.200:8000",
    "http://192.168.153.62:8000",
    "http://0.0.0.0:8000",
    "http://192.168.1.103:8000",
    # Cloudflare Tunnel sirve en HTTPS con subdominio aleatorio
    "https://*.trycloudflare.com",
    "https://*.cfargotunnel.com",
]

# Cloudflared termina el TLS y reenvía en HTTP al runserver/waitress local.
# Sin esto Django genera URLs http:// y puede fallar CSRF/sesiones detrás de https://.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Endurecimiento opcional sin romper HTTP local:
# En .env prod con HTTPS -> USE_HTTPS=True, SECURE_SSL_REDIRECT=True
_USE_HTTPS_LOCAL = os.environ.get("USE_HTTPS", "False").lower() == "true"
if _USE_HTTPS_LOCAL:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() == "true"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

AUTH_SERVER_URL = os.environ.get("AUTH_SERVER_URL", "http://192.168.1.103:8000")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "Matris"),
        "USER": os.environ.get("DB_USER", "root"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        # Persistentes 60s: evita abrir/cerrar conexión MySQL por request
        # (wait_timeout del servidor es de horas; 4 hilos waitress = ~4 conns).
        "CONN_MAX_AGE": 60,
    }
}


# ── Configuración de correo saliente (SMTP) ────────────────────────────────
# NOTA: POP es para RECIBIR correos. Django usa SMTP para ENVIAR correos.
# Tu servidor de correo POP también tiene SMTP — usa esas credenciales aquí.
#
# Opción A — Outlook / Office 365:
#   EMAIL_HOST = 'smtp.office365.com'  PORT=587  TLS=True
#
# Opción B — Servidor propio / POP corporativo:
#   EMAIL_HOST = 'mail.tudominio.com'  PORT=587  TLS=True
#   (o PORT=465  EMAIL_USE_SSL=True  EMAIL_USE_TLS=False)
# ──────────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 465))
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "True").lower() == "true"
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", EMAIL_HOST_USER)
EMAIL_ERP_ANALISTA = os.environ.get("EMAIL_ERP_ANALISTA", "")

EMAIL_SUBJECT_PREFIX = "[Helpdesk AI]"

# Timeout SMTP explícito: sin esto smtplib puede bloquear el worker minutos.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))

# --- URL BASE Envvio de correo---
SITE_URL = os.environ.get("SITE_URL", "http://192.168.1.103:8081")


INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")

# --- Alertas de error 500 (solo con DEBUG=False) ---
# ADMIN_EMAILS="a@x.com,b@x.com" en .env. Requiere SMTP configurado.
_admins = [a.strip() for a in os.environ.get("ADMIN_EMAILS", "").split(",") if a.strip()]
ADMINS = [(a.split("@")[0], a) for a in _admins]
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", EMAIL_HOST_USER)

# --- LOGGING ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        # File handler removed per user request
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "mail_admins": {
            "level": "ERROR",
            "class": "django.utils.log.AdminEmailHandler",
            "include_html": False,
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["mail_admins", "console"],
            "level": "ERROR",
            "propagate": False,
        },
        "app.iahelp": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}
