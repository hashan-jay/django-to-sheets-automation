from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0018_google_sheet_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="auto_sync",
            field=models.BooleanField(default=True),
        ),
    ]
