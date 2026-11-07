import os
import sys

from django.apps import AppConfig


class BrandsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "brands"

    def ready(self) -> None:
        if "runserver" not in sys.argv:
            return
        # The autoreloader parent must not start a second poller. --noreload has no child process.
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
            return
        from brands.poller import start_poller

        start_poller()
