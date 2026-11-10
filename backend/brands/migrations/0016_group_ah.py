from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0015_sheet_start_rows"),
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
                    ("GROUP AH", "GROUP AH"),
                ],
                max_length=32,
            ),
        ),
    ]
