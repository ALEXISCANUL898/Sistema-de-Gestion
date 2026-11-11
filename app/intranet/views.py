from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Publication
from django import forms
from django.contrib import messages

class PublicationForm(forms.ModelForm):
    class Meta:
        model = Publication
        fields = ['title', 'description', 'image']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Título'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Descripción', 'rows': 4}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean_image(self):
        from app.cuentas.validators import validar_imagen
        return validar_imagen(self.cleaned_data.get("image"))

def publication_list(request):
    publications = Publication.objects.all()
    return render(request, 'intranet/list.html', {'publications': publications})

@login_required(login_url='/intranet/login/')
def publication_create(request):
    if request.method == 'POST':
        form = PublicationForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Publicación creada con éxito.")
            return redirect('intranet_mural')
    else:
        form = PublicationForm()
    
    return render(request, 'intranet/create.html', {'form': form})
