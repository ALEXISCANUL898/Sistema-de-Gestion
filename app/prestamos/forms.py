from django import forms
from .models import SolicitudPrestamo
from datetime import date


class SolicitudPrestamoForm(forms.ModelForm):
    acepto_terminos = forms.BooleanField(
        required=True,
        label='Acepto los términos de responsabilidad',
        error_messages={'required': 'Debes aceptar la cláusula de responsabilidad para continuar.'}
    )

    class Meta:
        model = SolicitudPrestamo
        fields = [
            'nombre_completo', 'area_departamento', 'puesto', 'correo', 'telefono',
            'fecha_inicio_uso', 'fecha_devolucion', 'hora_devolucion',
            'contratista', 'motivo_uso', 'equipo', 'marca', 'modelo_equipo',
            'potencia_nominal', 'tipo_bateria', 'acepto_terminos',
        ]
        widgets = {
            'nombre_completo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. Juan Carlos Pérez López',
                'autocomplete': 'name',
            }),
            'area_departamento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. Dirección Administrativa',
            }),
            'puesto': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. Residente de obra',
            }),
            'correo': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'correo@empresa.com',
                'autocomplete': 'email',
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. 999-123-4567',
            }),
            'fecha_inicio_uso': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'fecha_devolucion': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'hora_devolucion': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control',
            }),
            'contratista': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. Constructora XYZ',
            }),
            'equipo': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'marca': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'modelo_equipo': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'potencia_nominal': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'tipo_bateria': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'motivo_uso': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describa el motivo por el que necesita el equipo...',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        fecha_inicio = cleaned_data.get('fecha_inicio_uso')
        fecha_devolucion = cleaned_data.get('fecha_devolucion')
        hoy = date.today()

        if fecha_inicio:
            if fecha_inicio < hoy:
                self.add_error('fecha_inicio_uso', 'La fecha de inicio no puede ser anterior a hoy.')

        if fecha_inicio and fecha_devolucion:
            if fecha_devolucion < fecha_inicio:
                self.add_error('fecha_devolucion', 'La fecha de devolución debe ser igual o posterior a la fecha de inicio.')

        return cleaned_data
