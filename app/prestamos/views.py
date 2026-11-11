from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages
from django.utils import timezone
from .models import SolicitudPrestamo
from .forms import SolicitudPrestamoForm


@login_required
def prestamo_solicitud(request):
    """Vista para crear una nueva solicitud de préstamo de equipo."""
    if request.method == 'POST':
        form = SolicitudPrestamoForm(request.POST)
        if form.is_valid():
            solicitud = form.save(commit=False)
            solicitud.usuario = request.user
            solicitud.fecha_hora_aceptacion = timezone.now()
            solicitud.save()
            return redirect('prestamo_comprobante', folio=solicitud.folio)
        else:
            messages.error(request, 'Por favor corrige los errores en el formulario.')
    else:
        form = SolicitudPrestamoForm()

    return render(request, 'prestamos/prestamo_solicitud.html', {'form': form})


@login_required
def prestamo_comprobante(request, folio):
    """Muestra el comprobante con folio después de enviar la solicitud."""
    solicitud = get_object_or_404(SolicitudPrestamo, folio=folio)
    return render(request, 'prestamos/prestamo_comprobante.html', {'solicitud': solicitud})


@login_required
def prestamo_admin_panel(request):
    """Panel de administrador para gestionar solicitudes de préstamo."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, 'Acceso restringido. Se requieren permisos de administrador.')
        return redirect('prestamo_solicitud')

    solicitudes = SolicitudPrestamo.objects.all()

    # Filtros opcionales por estado
    estado_filtro = request.GET.get('estado', '')
    if estado_filtro:
        solicitudes = solicitudes.filter(estado=estado_filtro)

    # Búsqueda por nombre o folio
    busqueda = request.GET.get('q', '')
    if busqueda:
        solicitudes = solicitudes.filter(
            nombre_completo__icontains=busqueda
        ) | SolicitudPrestamo.objects.filter(folio__icontains=busqueda)

    total_count = solicitudes.count()

    paginator = Paginator(solicitudes, 10)
    page = request.GET.get('page')
    try:
        solicitudes_paginated = paginator.page(page)
    except PageNotAnInteger:
        solicitudes_paginated = paginator.page(1)
    except EmptyPage:
        solicitudes_paginated = paginator.page(paginator.num_pages)

    return render(request, 'prestamos/prestamo_admin.html', {
        'solicitudes': solicitudes_paginated,
        'estado_filtro': estado_filtro,
        'busqueda': busqueda,
        'total': total_count,
        'estados': SolicitudPrestamo.ESTADO_CHOICES,
    })


@login_required
def prestamo_cambiar_estado(request, folio):
    """Cambia el estado de una solicitud (solo admin)."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, 'Acceso restringido.')
        return redirect('prestamo_solicitud')

    solicitud = get_object_or_404(SolicitudPrestamo, folio=folio)

    if request.method == 'POST':
        nuevo_estado = request.POST.get('estado')
        estados_validos = [c[0] for c in SolicitudPrestamo.ESTADO_CHOICES]
        if nuevo_estado in estados_validos:
            solicitud.estado = nuevo_estado
            solicitud.save()
            messages.success(request, f'Estado actualizado a "{solicitud.get_estado_display()}".')
        else:
            messages.error(request, 'Estado no válido.')

    return redirect('prestamo_admin_panel')


@login_required
def prestamo_imprimir(request, folio):
    """Vista de impresión del comprobante con cláusula de responsabilidad."""
    solicitud = get_object_or_404(SolicitudPrestamo, folio=folio)
    return render(request, 'prestamos/prestamo_imprimir.html', {'solicitud': solicitud})
