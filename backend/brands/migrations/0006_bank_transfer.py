from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("brands", "0005_brand_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankTransfer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transfer_date", models.DateField(db_index=True)),
                ("created_on", models.DateField(db_index=True)),
                ("from_bank_name", models.CharField(max_length=128)),
                ("from_account_name", models.CharField(max_length=255)),
                ("to_bank_name", models.CharField(max_length=128)),
                ("to_account_name", models.CharField(max_length=255)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="bank_transfers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="banktransfer",
            index=models.Index(fields=["from_bank_name", "from_account_name", "transfer_date"], name="bank_xfer_from_day"),
        ),
        migrations.AddIndex(
            model_name="banktransfer",
            index=models.Index(fields=["to_bank_name", "to_account_name", "transfer_date"], name="bank_xfer_to_day"),
        ),
    ]
