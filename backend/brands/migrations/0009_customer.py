from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("brands", "0008_drop_bank_account_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=64)),
                ("username", models.CharField(blank=True, max_length=128)),
                ("name", models.CharField(blank=True, max_length=255)),
                ("mobile", models.CharField(blank=True, max_length=64)),
                ("email", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(blank=True, max_length=32)),
                ("registered_at", models.DateTimeField(blank=True, null=True)),
                ("visited_at", models.DateTimeField(blank=True, null=True)),
                ("lifetime_deposit", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("lifetime_deposit_count", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "brand",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="customers", to="brands.brand"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CustomerSync",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("next_page", models.PositiveIntegerField(default=0)),
                ("total_pages", models.PositiveIntegerField(default=0)),
                ("message", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "brand",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="customer_sync", to="brands.brand"),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(fields=("brand", "external_id"), name="uniq_brand_customer"),
        ),
        migrations.AddIndex(
            model_name="customer",
            index=models.Index(fields=["brand", "registered_at"], name="customer_brand_registered"),
        ),
        migrations.AddIndex(
            model_name="customer",
            index=models.Index(fields=["username"], name="customer_username"),
        ),
    ]
