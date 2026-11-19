from django.db import migrations, models


def keep_kaboom77(apps, schema_editor):
    Brand = apps.get_model("brands", "Brand")
    Brand.objects.filter(group="GROUP AH").update(group="KABOOM77")
    Brand.objects.filter(name="WOOSPIN").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0022_sheet_end_rows"),
    ]

    operations = [
        migrations.AlterField(
            model_name="brand",
            name="group",
            field=models.CharField(
                blank=True,
                choices=[
                    ("SOLO - KABOOM", "SOLO - KABOOM"),
                    ("GROUP AK", "GROUP AK"),
                    ("GROUP U", "GROUP U"),
                    ("GROUP Y", "GROUP Y"),
                    ("KABOOM77", "KABOOM77"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(keep_kaboom77, migrations.RunPython.noop),
    ]
