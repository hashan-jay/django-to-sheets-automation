"""Redis snapshot of a day's transactions.

The live screen reads this instead of scanning Postgres on every refresh.
A revision counter lets the browser skip the payload when nothing changed.
The snapshot body is compressed, and this process keeps the parsed copy for
the current revision so a live refresh does not download and decode it again.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import zlib
from datetime import date

import redis
from django.conf import settings

_client: redis.Redis | None = None
_binary: redis.Redis | None = None
_down_until = 0.0
_lock = threading.Lock()
_parsed: dict[str, tuple[str, dict]] = {}
_MAX_CACHED_DAYS = 3


def _mark_down() -> None:
    global _client, _binary, _down_until
    _down_until = time.monotonic() + 2
    clients = (_client, _binary)
    _client = None
    _binary = None
    for client in clients:
        if client is None:
            continue
        try:
            client.close()
        except redis.RedisError:
            pass


def _redis_url() -> str:
    return getattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/0")


def _connect(*, decode: bool) -> redis.Redis:
    if time.monotonic() < _down_until:
        raise redis.ConnectionError("Redis is cooling down after a connection error")
    return redis.Redis.from_url(
        _redis_url(),
        decode_responses=decode,
        # This host runs Redis 5, which does not accept the RESP3 HELLO command.
        protocol=2,
        socket_connect_timeout=0.3,
        socket_timeout=3,
        health_check_interval=30,
        max_connections=16,
    )


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = _connect(decode=True)
    return _client


def _raw_redis() -> redis.Redis:
    global _binary
    if time.monotonic() < _down_until:
        raise redis.ConnectionError("Redis is cooling down after a connection error")
    if _binary is None:
        _binary = _connect(decode=False)
    return _binary


def ping() -> bool:
    if time.monotonic() < _down_until:
        return False
    try:
        return bool(_redis().ping())
    except redis.RedisError:
        _mark_down()
        return False


def _keys(day: date) -> tuple[str, str, str, str]:
    iso = day.isoformat()
    return (
        f"brands:snap:syd:{iso}",
        f"brands:hash:syd:{iso}",
        f"brands:rev:syd:{iso}",
        f"brands:mark:syd:{iso}",
    )


def revision(day: date) -> str | None:
    if time.monotonic() < _down_until:
        return None
    try:
        value = _redis().get(_keys(day)[2])
    except redis.RedisError:
        _mark_down()
        return None
    if value is None:
        return None
    return str(value)


def _recall(day: date, rev: str) -> dict | None:
    with _lock:
        hit = _parsed.get(day.isoformat())
    if hit and hit[0] == rev:
        return hit[1]
    return None


def _remember(day: date, rev: str, data: dict) -> None:
    iso = day.isoformat()
    with _lock:
        _parsed[iso] = (rev, data)
        if len(_parsed) > _MAX_CACHED_DAYS:
            for old in sorted(_parsed)[:-_MAX_CACHED_DAYS]:
                _parsed.pop(old, None)


def _decode_snapshot(raw: bytes) -> dict | None:
    if raw[:1] != b"{":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            return None
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def snapshot(day: date) -> dict | None:
    if time.monotonic() < _down_until:
        return None
    rev = revision(day)
    if rev is not None:
        cached = _recall(day, rev)
        if cached is not None:
            cached["revision"] = int(rev or 0)
            return cached
    snap_key, _, rev_key, _ = _keys(day)
    try:
        raw, rev_bytes = _raw_redis().mget(snap_key, rev_key)
    except redis.RedisError:
        _mark_down()
        return None
    if not raw:
        return None
    plain = raw[:1] == b"{"
    data = _decode_snapshot(raw)
    if data is None:
        return None
    if rev_bytes:
        rev = rev_bytes.decode()
    if plain:
        try:
            _raw_redis().set(snap_key, zlib.compress(raw, level=1), ex=172800)
        except redis.RedisError:
            pass
    if rev is not None:
        _remember(day, rev, data)
    data["revision"] = int(rev or 0)
    return data


def has_snapshot(day: date) -> bool:
    if time.monotonic() < _down_until:
        return False
    try:
        return bool(_redis().exists(_keys(day)[0]))
    except redis.RedisError:
        _mark_down()
        return False


def same(key: str, digest: str) -> bool:
    """True when Redis already stored this exact value."""
    if time.monotonic() < _down_until:
        return False
    try:
        return _redis().get(key) == digest
    except redis.RedisError:
        _mark_down()
        return False


def store(key: str, digest: str) -> None:
    if time.monotonic() < _down_until:
        return
    try:
        _redis().set(key, digest, ex=172800)
    except redis.RedisError:
        _mark_down()


def publish(day: date, rows: list, brands: list, marker: str) -> int | None:
    """Store the day snapshot. A newer marker always wins, so a slow read cannot overwrite fresh rows."""
    if time.monotonic() < _down_until:
        return None
    snap_key, hash_key, rev_key, mark_key = _keys(day)
    body = json.dumps({"rows": rows, "brands": brands}, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(body).hexdigest()
    packed = zlib.compress(body, level=1)
    try:
        client = _redis()
        current_mark = client.get(mark_key)
        if current_mark is not None and current_mark >= marker:
            current_rev = client.get(rev_key)
            return int(current_rev or 0)
        if client.get(hash_key) == digest:
            client.set(mark_key, marker, ex=172800)
            current_rev = client.get(rev_key)
            if current_rev is not None:
                _remember(day, str(current_rev), {"rows": rows, "brands": brands})
            return int(current_rev or 0)
        pipe = _raw_redis().pipeline(transaction=True)
        pipe.set(snap_key, packed, ex=172800)
        pipe.set(hash_key, digest, ex=172800)
        pipe.set(mark_key, marker, ex=172800)
        pipe.incr(rev_key)
        pipe.expire(rev_key, 172800)
        _stored, _hash_set, _mark_set, new_rev, _expired = pipe.execute()
        _remember(day, str(int(new_rev or 0)), {"rows": rows, "brands": brands})
        return int(new_rev or 0)
    except redis.RedisError:
        _mark_down()
        return None
