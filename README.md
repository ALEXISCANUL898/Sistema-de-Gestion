# Matris Platform — Helpdesk Interno con IA

> Sistema interno de mesa de ayuda potenciado con IA y múltiples módulos de gestión empresarial: Enkontrol, almacén de vales, reservaciones, préstamos, intranet, catálogos y auditoría.

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Django 5.0 · Python 3.14 |
| Base de datos | MySQL (`Matris`) · PyMySQL |
| API | Django REST Framework + SimpleJWT |
| IA | Groq API (compatible OpenAI) — clasificación y respuesta automática de tickets |
| Reportes | WeasyPrint (PDF) · openpyxl · ReportLab (Excel) |
| Datos/análisis | pandas · numpy |
| Servidor prod. | Waitress detrás de proxy reverso |
| Archivos estáticos | WhiteNoise |

## Arranque rápido

```bat
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
REM Completar .env con tus valores (ver sección Variables de entorno)
python manage.py migrate
python manage.py runserver
```

En producción usa `deploy.bat`, que crea el entorno, instala dependencias, aplica migraciones y recolecta estáticos.

## Variables de entorno

Copia `.env.example` → `.env` y completa los valores:

```env
# Django
DEBUG=False
SECRET_KEY=                      # Clave secreta Django (obligatorio)
USE_HTTPS=False
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0
ALLOWED_HOSTS_EXTRA=             # Hosts adicionales separados por coma

# Base de datos MySQL
DB_NAME=Matris
DB_USER=app_tickets
DB_PASSWORD=                     # Contraseña del usuario MySQL
DB_HOST=127.0.0.1
DB_PORT=3306

# Correo electrónico
EMAIL_HOST=
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_USE_TLS=False
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=
SUPPORT_EMAIL=
EMAIL_ERP_ANALISTA=
SERVER_EMAIL=
ADMIN_EMAILS=                    # Lista de correos admin separados por coma
EMAIL_TIMEOUT=10

# Seguridad / API interna
INTERNAL_API_KEY=                # Clave para comunicación entre servicios internos
AUTH_SERVER_URL=http://...       # URL del servidor de autenticación
SITE_URL=http://...              # URL pública del sitio

# IA — Groq
GROQ_API_KEY=                    # Obtener en https://console.groq.com

# Seguridad de login
LOGIN_MAX_INTENTOS=5
LOGIN_BLOQUEO_MINUTOS=15
```

## Estructura del proyecto

```
app/                     8 apps Django (una por dominio de negocio)
  iahelp/                Núcleo: Helpdesk IA + integración Enkontrol
    vistas/              Vistas HTTP agrupadas por dominio
    servicios/           IA, correo, cola en segundo plano, datos Enkontrol
    prompts/             Textos de sistema enviados al modelo
    api/                 API de login/permisos (DRF)
    infraestructura/     Middleware de permisos, decoradores, router de BD
    migrations/          Migraciones (no mover)
  almacen_vales/         Vales, entregas y firmas
  auditoria/             Bitácora de acciones
  catalogos/             Empresas, áreas, planos, unidades, materiales
  cuentas/               Autenticación centralizada, perfiles, PIN, throttle
  intranet/              Publicaciones del mural interno
  prestamos/             Solicitudes de préstamo
  reservas/              Reservaciones de espacios/recursos
helpTicket/              Configuración del proyecto (settings/, urls.py, wsgi/asgi)
templates/               Plantillas HTML por módulo (soporte/, almacen/, ...)
static/                  CSS, JS, iconos e imágenes
scripts/                 Utilidades operativas (ej. respaldo_mysql.py)
docs/                    Documentación técnica del proyecto
backups/                 Respaldos locales (no versionado)
```

## Respaldos

Para respaldos de MySQL usa el script incluido:

```bat
python scripts/respaldo_mysql.py
```

Los archivos generados se guardan en `backups/` (carpeta excluida del repositorio).

## Documentación

- [Arquitectura](docs/ARQUITECTURA.md)
- [Módulos y responsabilidades](docs/MODULOS.md)
- [Convenciones de código](docs/CONVENCIONES.md)
- [Despliegue y operación](docs/DESPLIEGUE.md)
