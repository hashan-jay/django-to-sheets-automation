from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0017_three_google_sheets"),
    ]

    operations = [
        migrations.AddField(
            model_name="googlesheetsetting",
            name="sheet_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
