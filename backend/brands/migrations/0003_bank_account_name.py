from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0002_transaction_bank_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="bank_account_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name="CompanyBank",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=32, unique=True)),
                ("bank_name", models.CharField(blank=True, max_length=128)),
                ("account_name", models.CharField(blank=True, max_length=255)),
            ],
        ),
    ]
