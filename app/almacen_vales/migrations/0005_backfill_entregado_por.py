# Rellena entregado_por en entregas creadas antes de que existiera el campo:
# usa el asignado vigente del vale y, si no hay, quien la registró.
from django.db import migrations


def backfill_entregado_por(apps, schema_editor):
    Entrega = apps.get_model("almacen_vales", "Entrega")
    AsignacionVale = apps.get_model("almacen_vales", "AsignacionVale")
    n = 0
    for e in Entrega.objects.filter(entregado_por__isnull=True).select_related("vale", "perfil"):
        vig = (AsignacionVale.objects.filter(vale_id=e.vale_id, vigente=True)
               .order_by("-fecha").values_list("asignado_a_id", flat=True).first())
        quien = vig or e.perfil_id
        if quien:
            Entrega.objects.filter(pk=e.pk).update(entregado_por_id=quien)
            n += 1
    if n:
        print(f"\n  [0005] entregas con entregado_por rellenado: {n}")


class Migration(migrations.Migration):

    dependencies = [
        ("almacen_vales", "0004_entrega_entregado_por_alter_entrega_perfil"),
    ]

    operations = [
        migrations.RunPython(backfill_entregado_por, migrations.RunPython.noop),
    ]
