from django.db import migrations, models


def seed_groups(apps, schema_editor):
    GroupSetting = apps.get_model("brands", "GroupSetting")
    GroupSetting.objects.get_or_create(code="KABOOM77")
    GroupSetting.objects.get_or_create(code="BETMETH")


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0023_kaboom77_only"),
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
                    ("BETMETH", "BETMETH"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="GroupSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32, unique=True)),
                ("google_email", models.EmailField(blank=True, max_length=254)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.RunPython(seed_groups, migrations.RunPython.noop),
    ]
