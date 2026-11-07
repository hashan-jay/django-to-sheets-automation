from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0010_customer_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="lifetime_withdraw",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="customer",
            name="lifetime_withdraw_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="customer",
            name="withdraw_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
