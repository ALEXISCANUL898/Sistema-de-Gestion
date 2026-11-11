from django import forms
from .models import Empresa, Area, Plano, Unidad, Material, Configuracion


CSS_INPUT = "form-control"
CSS_CHECK = "form-check-input"


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ["nombre", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": CSS_INPUT, "placeholder": "Nombre de la empresa"}),
            "activa": forms.CheckboxInput(attrs={"class": CSS_CHECK}),
        }


class AreaForm(forms.ModelForm):
    class Meta:
        model = Area
        fields = ["nombre", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": CSS_INPUT, "placeholder": "Nombre del área"}),
            "activa": forms.CheckboxInput(attrs={"class": CSS_CHECK}),
        }


class PlanoForm(forms.ModelForm):
    class Meta:
        model = Plano
        fields = ["nombre", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": CSS_INPUT, "placeholder": "Nombre del plano / proyecto"}),
            "activa": forms.CheckboxInput(attrs={"class": CSS_CHECK}),
        }


class UnidadForm(forms.ModelForm):
    class Meta:
        model = Unidad
        fields = ["nombre", "abreviatura", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": CSS_INPUT, "placeholder": "Ej. Kilogramo"}),
            "abreviatura": forms.TextInput(attrs={"class": CSS_INPUT, "placeholder": "Ej. kg"}),
            "activa": forms.CheckboxInput(attrs={"class": CSS_CHECK}),
        }


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ["descripcion", "unidad_sugerida", "activa"]
        widgets = {
            "descripcion": forms.TextInput(attrs={"class": CSS_INPUT, "placeholder": "Descripción del material"}),
            "unidad_sugerida": forms.Select(attrs={"class": "form-select"}),
            "activa": forms.CheckboxInput(attrs={"class": CSS_CHECK}),
        }
        help_texts = {
            "descripcion": "El folio (MAT-XXXX) se asigna automáticamente al guardar.",
        }


class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Configuracion
        fields = [
            "logo",
            "max_filas_vale",
            "semaforo_amarillo_horas",
            "semaforo_rojo_horas",
            "inactividad_timeout_min",
        ]
        widgets = {
            "logo": forms.ClearableFileInput(attrs={"class": CSS_INPUT, "accept": "image/*"}),
            "max_filas_vale": forms.NumberInput(attrs={"class": CSS_INPUT, "min": 1, "max": 30}),
            "semaforo_amarillo_horas": forms.NumberInput(attrs={"class": CSS_INPUT, "min": 1}),
            "semaforo_rojo_horas": forms.NumberInput(attrs={"class": CSS_INPUT, "min": 1}),
            "inactividad_timeout_min": forms.NumberInput(attrs={"class": CSS_INPUT, "min": 1}),
        }

    def clean(self):
        data = super().clean()
        amarillo = data.get("semaforo_amarillo_horas")
        rojo = data.get("semaforo_rojo_horas")
        if amarillo and rojo and amarillo >= rojo:
            raise forms.ValidationError(
                "El umbral amarillo debe ser menor que el rojo."
            )
        return data

    def clean_logo(self):
        from app.cuentas.validators import validar_imagen
        return validar_imagen(self.cleaned_data.get("logo"))
