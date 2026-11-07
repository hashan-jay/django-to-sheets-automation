from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0012_bank_transfer_remarks"),
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
                ],
                max_length=32,
            ),
        ),
    ]
