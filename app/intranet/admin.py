from django.contrib import admin
from .models import Publication

@admin.register(Publication)
class PublicationAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at')
    search_fields = ('title', 'description')
