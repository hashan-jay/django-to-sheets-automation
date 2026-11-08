from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0013_group_y"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoogleSheetSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sheet_url", models.URLField(blank=True, max_length=500)),
                ("last_error", models.TextField(blank=True)),
                ("last_written_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="SheetExport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("written_at", models.DateTimeField(auto_now_add=True)),
                (
                    "transaction",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sheet_export",
                        to="brands.transaction",
                    ),
                ),
            ],
        ),
    ]
