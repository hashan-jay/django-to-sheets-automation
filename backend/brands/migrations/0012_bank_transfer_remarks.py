from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0011_customer_lifetime_withdraw"),
    ]

    operations = [
        migrations.AddField(
            model_name="banktransfer",
            name="remarks",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
