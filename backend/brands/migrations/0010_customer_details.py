from django.db import migrations, models


def rewind_customer_sync(apps, schema_editor):
    CustomerSync = apps.get_model("brands", "CustomerSync")
    CustomerSync.objects.update(next_page=0)


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0009_customer"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="account_type",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="customer",
            name="cash",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="customer",
            name="cash_site_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customer",
            name="referrer_name",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="customer",
            name="referrer_code",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="customer",
            name="tags",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customer",
            name="bank_name",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="customer",
            name="bank_account_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customer",
            name="bank_account_number",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="customer",
            name="bank_bsb",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="customer",
            name="pay_id",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="customer",
            name="bank_locked",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(rewind_customer_sync, migrations.RunPython.noop),
    ]
