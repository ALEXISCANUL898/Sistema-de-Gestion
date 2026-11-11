"""FULLTEXT en Material.descripcion para el buscador (fase 2).

Acelera material_buscar (?q=) de full-scan LIKE a índice FULLTEXT InnoDB.
Reversible. No toca datos.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalogos", "0007_alter_material_folio"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE FULLTEXT INDEX mat_desc_ftx ON catalogos_material (descripcion);",
            reverse_sql="DROP INDEX mat_desc_ftx ON catalogos_material;",
        ),
    ]
