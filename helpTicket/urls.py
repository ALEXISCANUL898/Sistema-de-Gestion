"""
URL configuration for helpTicket project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from app.cuentas.views import serve_media_protegida

urlpatterns = [    path("admin/", admin.site.urls),
    path("cuentas/", include("app.cuentas.urls", namespace="cuentas")),
    path("almacen/", include("app.almacen_vales.urls", namespace="almacen")),
    path("catalogos/", include("app.catalogos.urls", namespace="catalogos")),
    path("iahelp/", include("app.iahelp.urls")),
    path("reservaciones/", include("app.reservas.urls")),
    path("intranet/", include("app.intranet.urls")),
    path("prestamos/", include("app.prestamos.urls")),
    path("", include("app.iahelp.urls")),
]

# Media: público solo lo no sensible (logos, publicaciones del mural).
# Firmas (firmas_perfiles/, firmas_vales/) solo vía vista protegida con login.
if settings.DEBUG:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]
else:
    urlpatterns += [
        re_path(r'^media/(?P<path>(config|intranet)/.*)$', serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
        path("media/<path:path>", serve_media_protegida, name="media_protegida"),
    ]
