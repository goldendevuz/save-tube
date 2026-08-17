"""Redis asosidagi dashboard statistikasi uchun yordamchi.

Butun funktsional xotira Redis'da saqlanadi. Redis ishlamayotgan bo'lsa,
funktsiyalar xavfsiz tarzda Hech narsa qilmaydi (DB bilan to'g'ridan-to'g'ri
hisoblash davom etadi) — dashboard hech qachon yiqilmaydi.

Asosiy tushunchalar:
  - row cache  -> hisoblangan joriy yig'indilar (scope bo'yicha).
  - snapshot   -> har kunning yig'indilari; "7 kun avval" qiymatini solishtirish
                  shu snapshotlardan olinadi.
"""

import datetime
import json
import os

_row_cache_prefix = "st:row:"
_snapshot_prefix = "st:snap:"


def _client():
    import redis as _redis
    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1")
    return _redis.Redis.from_url(url, decode_responses=True)


def row_cache_set(scope, totals):
    try:
        _client().set(f"{_row_cache_prefix}{scope}", json.dumps(totals))
    except Exception:
        pass


def row_cache_get(scope):
    try:
        raw = _client().get(f"{_row_cache_prefix}{scope}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def row_cache_delete(scope):
    try:
        _client().delete(f"{_row_cache_prefix}{scope}")
    except Exception:
        pass


def snapshot_set(scope, day, totals):
    try:
        _client().set(f"{_snapshot_prefix}{scope}:{day.isoformat()}", json.dumps(totals))
    except Exception:
        pass


def snapshot_get(scope, day):
    try:
        raw = _client().get(f"{_snapshot_prefix}{scope}:{day.isoformat()}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def today_local():
    return datetime.date.today()


def day_offset(day, offset):
    return day + datetime.timedelta(days=offset)