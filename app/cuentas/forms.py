from django import forms
from django.contrib.auth import authenticate
from .models import PIN_DENEGADOS

# PIN 4 dígitos (operativa actual). Bloqueo: base exigida + repeticiones/secuencias.
PIN_TRIVIAL_EXTENDIDO = set(PIN_DENEGADOS) | {
    "2222", "3333", "4444", "5555", "6666", "8888", "9999", "4321",
}


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "Nombre de usuario",
            "autofocus": True,
        }),
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "Contraseña",
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")
        if username and password:
            self.user = authenticate(username=username, password=password)
            if self.user is None:
                raise forms.ValidationError("Credenciales incorrectas.")
            if not self.user.is_active:
                raise forms.ValidationError("Esta cuenta está desactivada.")
        return cleaned_data


class PINForm(forms.Form):
    pin = forms.CharField(
        label="PIN",
        min_length=4,
        max_length=4,
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg text-center",
            "placeholder": "● ● ● ●",
            "inputmode": "numeric",
            "pattern": "[0-9]{4}",
            "maxlength": "4",
            "autofocus": True,
        }),
    )

    def clean_pin(self):
        pin = self.cleaned_data.get("pin", "")
        if not pin.isdigit():
            raise forms.ValidationError("El PIN debe contener solo dígitos.")
        if pin in PIN_TRIVIAL_EXTENDIDO:
            raise forms.ValidationError("Este PIN no está permitido. Elige uno más seguro.")
        return pin


# ─── Formularios TI (Nivel 6) ──────────────────────────────────────────────────

from django.contrib.auth.models import User
from .models import CuentaExtension, Perfil


class CuentaCreateForm(forms.Form):
    """Crea un User + CuentaExtension en un solo formulario."""
    username = forms.CharField(
        label="Usuario (login)",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "nombre.usuario"}),
    )
    password = forms.CharField(
        label="Contraseña inicial",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Apellido",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Correo electrónico",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    nivel = forms.ChoiceField(
        label="Nivel de acceso",
        choices=CuentaExtension.NIVELES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso.")
        return username

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data["username"],
            password=data["password"],
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            email=data.get("email", ""),
        )
        CuentaExtension.objects.create(usuario=user, nivel=int(data["nivel"]))
        return user


class CuentaEditForm(forms.Form):
    """Edita nombre, email, nivel y estado activo de una cuenta."""
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    last_name = forms.CharField(
        label="Apellido",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Correo electrónico",
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    nivel = forms.ChoiceField(
        label="Nivel de acceso",
        choices=CuentaExtension.NIVELES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    is_active = forms.BooleanField(
        label="Cuenta activa",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    nueva_password = forms.CharField(
        label="Nueva contraseña (dejar vacío para no cambiar)",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    def save(self, user):
        data = self.cleaned_data
        user.first_name = data.get("first_name", "")
        user.last_name = data.get("last_name", "")
        user.email = data.get("email", "")
        user.is_active = data.get("is_active", True)
        if data.get("nueva_password"):
            user.set_password(data["nueva_password"])
        user.save()
        ext, _ = CuentaExtension.objects.get_or_create(usuario=user)
        ext.nivel = int(data["nivel"])
        ext.save(update_fields=["nivel"])
        return user


class PerfilForm(forms.ModelForm):
    """Crea/edita un Perfil. El PIN se maneja aparte."""
    class Meta:
        model = Perfil
        fields = ["nombre", "puesto", "firma", "rol_almacen", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "puesto": forms.TextInput(attrs={"class": "form-control"}),
            "firma": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "rol_almacen": forms.Select(attrs={"class": "form-select"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "rol_almacen": "Rol en almacén (solo cuentas Nivel 3)",
            "activo": "Perfil activo",
        }

    def clean_firma(self):
        from .validators import validar_imagen
        return validar_imagen(self.cleaned_data.get("firma"))


class PerfilPINForm(forms.Form):
    """Formulario para asignar / restablecer el PIN de un perfil."""
    nuevo_pin = forms.CharField(
        label="Nuevo PIN (4 dígitos)",
        min_length=4,
        max_length=4,
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg text-center",
            "inputmode": "numeric",
            "pattern": "[0-9]{4}",
            "maxlength": "4",
        }),
    )
    confirmar_pin = forms.CharField(
        label="Confirmar PIN",
        min_length=4,
        max_length=4,
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg text-center",
            "inputmode": "numeric",
            "pattern": "[0-9]{4}",
            "maxlength": "4",
        }),
    )

    def clean(self):
        data = super().clean()
        p1 = data.get("nuevo_pin", "")
        p2 = data.get("confirmar_pin", "")
        if not p1.isdigit():
            raise forms.ValidationError("El PIN debe contener solo dígitos.")
        if p1 in PIN_TRIVIAL_EXTENDIDO:
            raise forms.ValidationError("Este PIN no está permitido. Elige uno más seguro.")
        if p1 != p2:
            raise forms.ValidationError("Los PINs no coinciden.")
        return data
