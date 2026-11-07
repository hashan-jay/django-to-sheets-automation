from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0006_bank_transfer"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="bank_account_number",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="banktransfer",
            name="from_account_number",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="banktransfer",
            name="to_account_number",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(fields=["bank_name", "bank_account_number"], name="txn_bank_account_number"),
        ),
    ]
