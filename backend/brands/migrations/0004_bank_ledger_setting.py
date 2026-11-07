from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0003_bank_account_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankLedgerSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bank_name", models.CharField(max_length=128)),
                ("account_name", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("Block", "Block"),
                            ("Withdraw only", "Withdraw only"),
                            ("Deposit only", "Deposit only"),
                            ("Both", "Both"),
                            ("Active", "Active"),
                            ("Inactive", "Inactive"),
                        ],
                        max_length=32,
                    ),
                ),
                ("limit_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("bank_name", "account_name"), name="uniq_bank_ledger_account")
                ],
            },
        ),
    ]
