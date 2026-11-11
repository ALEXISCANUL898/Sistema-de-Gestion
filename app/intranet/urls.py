from django.urls import path
from . import views

urlpatterns = [
    path('', views.publication_list, name='intranet_mural'),
    path('create/', views.publication_create, name='intranet_create'),
]
