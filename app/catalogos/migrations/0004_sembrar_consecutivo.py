# Siembra el contador de consecutivos desde el máximo existente,
# para no reutilizar ni duplicar números tras el cambio a "al emitir".
from django.db import migrations


def sembrar_contador(apps, schema_editor):
    Vale = apps.get_model("almacen_vales", "Vale")
    Configuracion = apps.get_model("catalogos", "Configuracion")
    maximo = 0
    # En modelos históricos `objects` es un Manager plano: incluye eliminados.
    for (c,) in Vale.objects.values_list("consecutivo"):
        try:
            n = int(c)
        except (TypeError, ValueError):
            continue
        maximo = max(maximo, n)
    cfg, _ = Configuracion.objects.get_or_create(pk=1)
    if (cfg.ultimo_consecutivo or 0) < maximo:
        cfg.ultimo_consecutivo = maximo
        cfg.save(update_fields=["ultimo_consecutivo"])
    print(f"\n  [0003] ultimo_consecutivo sembrado en {max(cfg.ultimo_consecutivo, maximo)}")


class Migration(migrations.Migration):

    dependencies = [
        ("catalogos", "0003_configuracion_ultimo_consecutivo"),
        ("almacen_vales", "0002_vale_dato_otro_vale_tipo_detalle_and_more"),
    ]

    operations = [
        migrations.RunPython(sembrar_contador, migrations.RunPython.noop),
    ]
