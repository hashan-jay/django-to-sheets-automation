import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from brands.models import Brand

BRANDS = (
    {"name": "KABOOM77", "prefix": "KABOOM77", "domain": "https://kaboom77.com", "group": "SOLO - KABOOM", "sort_order": 1},
)


class Command(BaseCommand):
    help = "Create the admin account and store brand API settings from the environment."

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
        password = os.getenv("ADMIN_PASSWORD", "").strip()
        if password and not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, email="")
            self.stdout.write(f"Created admin user {username}")
        elif User.objects.filter(username=username).exists():
            self.stdout.write(f"Admin user {username} already exists")
        else:
            self.stdout.write("ADMIN_PASSWORD is empty, so no admin user was created")

        for item in BRANDS:
            prefix = item["prefix"]
            exists = Brand.objects.filter(name=item["name"]).exists()
            defaults = {
                "domain": os.getenv(f"{prefix}_DOMAIN", item["domain"]).strip() or item["domain"],
                "group": item["group"],
                "is_active": True,
                "sort_order": item["sort_order"],
            }
            for field, env_name in (
                ("access_id", "ACCESS_ID"),
                ("merchant_id", "MERCHANT_ID"),
                ("token", "TOKEN"),
            ):
                value = os.getenv(f"{prefix}_{env_name}", "").strip()
                if value or not exists:
                    defaults[field] = value
            Brand.objects.update_or_create(name=item["name"], defaults=defaults)
        self.stdout.write(f"Stored {len(BRANDS)} brands")
