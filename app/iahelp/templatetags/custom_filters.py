from django import template

register = template.Library()

@register.filter
def porcentaje(valor, total):
    """Calcula el porcentaje de valor/total"""
    try:
        if total and int(total) > 0:
            return (int(valor) * 100) / int(total)
        return 0
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def clean_message(value):
    """Limpia los tags del sistema o de la IA del mensaje para mostrarlos al usuario de manera limpia."""
    if not isinstance(value, str):
        return value
    tags = ["[SISTEMA]", "[IA_REOPEN_GREETING]", "[RESOLUTION_PROPOSAL]", "[AUTO_CLOSED]", "[USER_CONFIRMED]"]
    cleaned = value
    for tag in tags:
        cleaned = cleaned.replace(tag, "")
    return cleaned.strip()

@register.simple_tag
def widthratio(value, total, max):
    """Calcula el ancho proporcional para una barra de progreso"""
    try:
        if total and int(total) > 0:
            return (int(value) * int(max)) / int(total)
        return 0
    except (ValueError, TypeError, ZeroDivisionError):
        return 0
