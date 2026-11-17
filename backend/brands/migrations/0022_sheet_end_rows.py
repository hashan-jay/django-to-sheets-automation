from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0021_sheet_write_toggles"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="deposit_end_row",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="googlesheetsetting",
            name="withdraw_end_row",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
