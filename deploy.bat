@echo off
echo ===================================================
echo Iniciando despliegue de Tickt Helpdesk (Django)
echo ===================================================

echo.
echo [1/5] Verificando Entorno Virtual...
IF NOT EXIST venv (
    echo Creando entorno virtual...
    python -m venv venv
) ELSE (
    echo Entorno virtual ya existe.
)

echo.
echo [2/5] Activando Entorno e Instalando Dependencias...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install waitress

echo.
echo [3/5] Aplicando Migraciones de Base de Datos...
echo Recomendado: respalda MySQL antes de migrar en produccion.
python manage.py check --deploy
python manage.py migrate

echo.
echo [4/5] Recolectando Archivos Estaticos...
python manage.py collectstatic --noinput

echo.
echo [5/5] Despliegue Preparado con Exito.
echo.
echo ===================================================
echo TERMINADO. Ahora puedes iniciar el servidor:
echo.
echo - Modo Desarrollo: python manage.py runserver
echo - Modo Produccion con waitress: waitress-serve --listen=0.0.0.0:8000 helpTicket.wsgi:application
echo   (no usar runserver en produccion)
echo ===================================================
pause
