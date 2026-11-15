from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0020_sheet_withdraw_default_1000"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="deposits_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="googlesheetsetting",
            name="withdrawals_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
