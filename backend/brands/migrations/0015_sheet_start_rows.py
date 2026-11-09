from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0014_google_sheet"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="deposit_start_row",
            field=models.PositiveIntegerField(default=105),
        ),
        migrations.AddField(
            model_name="googlesheetsetting",
            name="withdraw_start_row",
            field=models.PositiveIntegerField(default=1024),
        ),
    ]
