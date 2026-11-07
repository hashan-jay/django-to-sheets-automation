"""Keep today's transactions current, plus any date a signed-in user is viewing."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date

from django.conf import settings

from brands import livecache
from brands.models import sydney_today
from brands.services import sync_day

log = logging.getLogger("django")

_started = False
_guard = threading.Lock()
_watched: dict[date, float] = {}


def note_watch(day: date) -> None:
    _watched[day] = time.monotonic()


def active_dates() -> set[date]:
    now = time.monotonic()
    today = sydney_today()
    keep = {today}
    stale = [day for day, seen in _watched.items() if now - seen > 180]
    for day in stale:
        _watched.pop(day, None)
    keep.update(_watched)
    return keep


def start_poller() -> None:
    global _started
    with _guard:
        if _started:
            return
        _started = True
    if not livecache.ping():
        log.warning("Redis is not reachable at %s. Live reads will use Postgres until it is.", settings.REDIS_URL)
    thread = threading.Thread(target=_loop, name="brand-poller", daemon=True)
    thread.start()


def _loop() -> None:
    interval = max(1, int(getattr(settings, "BRANDS_POLL_SECONDS", 2)))
    while True:
        for day in sorted(active_dates()):
            try:
                sync_day(day, wait=False)
            except Exception:
                # The next pass retries. BrandSync stores API errors separately.
                pass
        time.sleep(interval)
