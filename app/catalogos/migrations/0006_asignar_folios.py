# Asigna folio MAT-XXXX a materiales que no tienen.
from django.db import migrations


def asignar_folios(apps, schema_editor):
    Material = apps.get_model("catalogos", "Material")
    n = 0
    for m in Material.objects.filter(folio="").order_by("pk"):
        Material.objects.filter(pk=m.pk).update(folio=f"MAT-{m.pk:04d}")
        n += 1
    # Por si hubo nulos
    for m in Material.objects.filter(folio__isnull=True).order_by("pk"):
        Material.objects.filter(pk=m.pk).update(folio=f"MAT-{m.pk:04d}")
        n += 1
    if n:
        print(f"\n  [0006] folios asignados: {n}")


class Migration(migrations.Migration):

    dependencies = [
        ("catalogos", "0005_alter_material_options_material_folio"),
    ]

    operations = [
        migrations.RunPython(asignar_folios, migrations.RunPython.noop),
    ]
