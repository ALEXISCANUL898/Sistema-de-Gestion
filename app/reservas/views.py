from django.shortcuts import render, redirect
from django.db import models
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import Reservacion
from .forms import ReservacionForm
from django.contrib import messages
from datetime import datetime

@login_required
def reserva_list(request):
    ahora = datetime.now()
    hoy = ahora.date()
    tiempo_actual = ahora.time()
    
    # Mostrar reservaciones futuras o que están ocurriendo hoy pero no han terminado
    reservas = Reservacion.objects.filter(
        models.Q(fecha__gt=hoy) | 
        models.Q(fecha=hoy, hora_fin__gte=tiempo_actual)
    ).order_by('fecha', 'hora_inicio')
    
    return render(request, 'reservas/reserva_list.html', {'reservas': reservas})

@login_required
def reserva_history(request):
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'Acceso restringido al historial.')
        return redirect('reserva_list')
        
    ahora = datetime.now()
    hoy = ahora.date()
    tiempo_actual = ahora.time()
    
    # Mostrar reservaciones de días pasados O de hoy que ya terminaron
    reservas_list = Reservacion.objects.filter(
        models.Q(fecha__lt=hoy) | 
        models.Q(fecha=hoy, hora_fin__lt=tiempo_actual)
    ).order_by('-fecha', '-hora_inicio')
    
    paginator = Paginator(reservas_list, 10)
    page = request.GET.get('page')
    try:
        reservas = paginator.page(page)
    except PageNotAnInteger:
        reservas = paginator.page(1)
    except EmptyPage:
        reservas = paginator.page(paginator.num_pages)
        
    return render(request, 'reservas/reserva_list.html', {
        'reservas': reservas, 
        'is_history': True
    })

@login_required
def reserva_create(request):
    if request.method == 'POST':
        form = ReservacionForm(request.POST)
        if form.is_valid():
        
            fecha = form.cleaned_data['fecha']
            sala = form.cleaned_data['sala']
            hora_inicio = form.cleaned_data['hora_inicio']
            hora_fin = form.cleaned_data['hora_fin']

            overlap = Reservacion.objects.filter(
                fecha=fecha,
                sala=sala
            ).filter(
                models.Q(hora_inicio__lt=hora_fin, hora_fin__gt=hora_inicio)
            ).exists()

            if overlap:
                messages.error(request, 'La sala ya está reservada en ese horario.')
            else:
                reserva = form.save(commit=False)
                reserva.usuario = request.user
                reserva.save()
                messages.success(request, 'Reservación realizada con éxito.')
                return redirect('reserva_list')
    else:
        form = ReservacionForm()
    return render(request, 'reservas/reserva_form.html', {'form': form})

@login_required
def reserva_delete(request, pk):
    reserva = Reservacion.objects.get(pk=pk)
    
   
    is_admin = request.user.is_staff or request.user.is_superuser
    if reserva.usuario != request.user and not is_admin:
        messages.error(request, 'No tienes permiso para cancelar esta reservación.')
        return redirect('reserva_list')

    if request.method == 'POST':
        reserva.delete()
        messages.success(request, 'Reservación cancelada correctamente.')
    return redirect('reserva_list')
