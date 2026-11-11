from django import forms
from .models import Reservacion
from datetime import datetime, date

class ReservacionForm(forms.ModelForm):
    class Meta:
        model = Reservacion
        fields = ['nombre', 'departamento', 'puesto', 'sala', 'fecha', 'hora_inicio', 'hora_fin']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'hora_inicio': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'hora_fin': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre completo'}),
            'departamento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Departamento'}),
            'puesto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Puesto'}),
            'sala': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        fecha = cleaned_data.get('fecha')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fin = cleaned_data.get('hora_fin')

        if fecha and hora_inicio and hora_fin:
            # 1. Validar que la fecha no haya pasado
            hoy = date.today()
            if fecha < hoy:
                raise forms.ValidationError("No puedes registrar una reservación para una fecha que ya pasó.")

            # 2. Si es hoy, validar que la hora no haya pasado
            if fecha == hoy:
                ahora = datetime.now().time()
                if hora_inicio < ahora:
                    raise forms.ValidationError("La hora de inicio ya ha pasado.")

            # 3. Validar que la hora de fin sea posterior a la de inicio
            if hora_fin <= hora_inicio:
                raise forms.ValidationError("La hora de finalización debe ser posterior a la hora de inicio.")

        return cleaned_data
