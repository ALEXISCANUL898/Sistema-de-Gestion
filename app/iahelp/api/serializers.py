from rest_framework import serializers
from django.contrib.auth.models import User
from ..models import Sistema, Rol, UsuarioSistema, Ticket


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email"]


class SistemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sistema
        fields = ["id", "nombre", "codigo", "url"]


class RolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = ["id", "nombre", "nivel_acceso"]


class UsuarioSistemaSerializer(serializers.ModelSerializer):
    sistema = SistemaSerializer(read_only=True)
    rol = RolSerializer(read_only=True)

    class Meta:
        model = UsuarioSistema
        fields = ["sistema", "rol"]


class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = [
            "id",
            "user",
            "title",
            "description",
            "category",
            "nivel",
            "nivel_usuario",
            "priority",
            "status",
            "ai_summary",
            "ai_suggested_response",
            "created_at",
            "updated_at",
            "usuario",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "ai_summary", "ai_suggested_response", "nivel_usuario"]
