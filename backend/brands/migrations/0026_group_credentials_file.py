from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0025_group_sheets"),
    ]

    operations = [
        migrations.AddField(
            model_name="groupsetting",
            name="credentials_file",
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
