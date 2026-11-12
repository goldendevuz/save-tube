"""
YouTube obunalarini CSV fayldan Channel jadvaliga import qilish.

CSV ustunlari: channel_id, title, username (@handle), channel_url, logo_url,
subs_display ("2.1K"), subs_count (raqam), description.

Qoidalar:
- Standart holat — DRY-RUN: bazaga hech narsa yozilmaydi, faqat hisobot chiqadi.
  Haqiqiy import uchun `--no-dry-run --user <username>` kerak.
- Mavjud kanallar (url_hash bo'yicha, @handle katta-kichik harfga e'tiborsiz)
  o'tkazib yuboriladi: ular o'chirilmaydi va o'zgartirilmaydi.
- Yaratishda tarmoqqa chiqilmaydi (fetch_url_meta / fetch_channel_stats o'chirilgan).
  Statistika faqat `--stats` bilan, kanallar orasida pauza qilib olinadi.
- Jarayon to'xtasa, holat fayli (`<csv>.import-state.json`) orqali qolgan joyidan
  davom etadi: qaysi kanallar shu import bilan yaratilgani va qaysilari uchun
  statistika olingani shu faylda saqlanadi.
- Haqiqiy importdan oldin core/backup.py orqali zaxira nusxa olinadi.
"""
import argparse
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from youtube.models import Channel

# https://www.youtube.com/@handle  yoki  https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx
URL_RE = re.compile(r"^https://www\.youtube\.com/(@[^/\s?#]+|channel/UC[\w\-]{22})$")
CHANNEL_ID_RE = re.compile(r"^UC[\w\-]{22}$")
SUBS_DISPLAY_RE = re.compile(r"^([\d.]+)\s*([KMB])?(?:\s*SUBSCRIBERS?)?$")
SUFFIX = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

STATE_FLUSH_EVERY = 25


# --------------------------------------------------------------------------- #
# Sof yordamchi funksiyalar (testlash oson bo'lishi uchun alohida)
# --------------------------------------------------------------------------- #
def parse_subs(subs_count, subs_display):
    """Obunachilar sonini aniq butun songa aylantiradi.

    Avval `subs_count` (raqam), bo'lmasa `subs_display` ("2.1K" -> 2100).
    Hech biri yaroqli bo'lmasa — 0.
    """
    raw = (subs_count or "").strip().replace(" ", "").replace(",", "")
    if raw:
        try:
            value = int(Decimal(raw))
            if value >= 0:
                return value
        except (InvalidOperation, ValueError):
            pass

    display = (subs_display or "").strip().upper().replace(",", ".")
    match = SUBS_DISPLAY_RE.match(display)
    if match:
        try:
            number = Decimal(match.group(1))
        except InvalidOperation:
            return 0
        return int(number * SUFFIX.get(match.group(2), 1))
    return 0


def clean_url(url):
    """Kanal havolasini normalizatsiya qiladi (modeldagi normalize_url bilan)."""
    url = (url or "").strip()
    if not url:
        return ""
    url = re.split(r"[?#]", url, maxsplit=1)[0]  # query/fragment (masalan ?si=...) ni kesamiz
    url = re.sub(r"^http://", "https://", url)
    url = re.sub(r"^https://youtube\.com", "https://www.youtube.com", url)
    return Channel().normalize_url(url)


def parse_row(row):
    """CSV qatorini tekshiradi.

    Qaytaradi: (data, None) yoki (None, xato_matni).
    """
    username = (row.get("username") or "").strip()
    channel_id = (row.get("channel_id") or "").strip()

    url = clean_url(row.get("channel_url"))
    if not url:
        # channel_url bo'sh bo'lsa, @handle yoki channel_id dan yasaymiz
        if username:
            handle = username if username.startswith("@") else f"@{username}"
            url = clean_url(f"https://www.youtube.com/{handle}")
        elif CHANNEL_ID_RE.match(channel_id):
            url = f"https://www.youtube.com/channel/{channel_id}"
    if not url:
        return None, "channel_url (yoki username/channel_id) yo'q"
    if not URL_RE.match(url):
        return None, f"noto'g'ri YouTube havolasi: {url[:80]}"

    title = (row.get("title") or "").strip()[:255] or username or None
    description = (row.get("description") or "").strip() or None

    return {
        "url": url,
        "title": title,
        "description": description,
        "subscriber_count": parse_subs(row.get("subs_count"), row.get("subs_display")),
    }, None


def quiet_save(channel):
    """Channel.save() ni tarmoqqa chiqmasdan chaqiradi.

    Channel.save() ichida fetch_url_meta() (yt-dlp) va fetch_channel_stats()
    bor. Instance darajasida o'chirib qo'yamiz — hash, checkout, audit jurnali
    va signallar odatdagidek ishlaydi.
    """
    channel.fetch_url_meta = lambda: None
    channel.fetch_channel_stats = lambda: None
    channel.save()


# --------------------------------------------------------------------------- #
# Holat fayli (davom ettirish uchun)
# --------------------------------------------------------------------------- #
class ImportState:
    def __init__(self, path):
        self.path = Path(path)
        self.created = []       # shu import yaratgan kanallar url_hash lari (tartib bilan)
        self.stats_done = set()  # statistikasi olingan kanallar
        self._dirty = False
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.created = list(data.get("created", []))
                self.stats_done = set(data.get("stats_done", []))
            except (OSError, ValueError):
                raise CommandError(f"Holat fayli buzilgan: {self.path} (o'chirib qayta urining)")
        self._created_set = set(self.created)

    def add_created(self, url_hash):
        if url_hash not in self._created_set:
            self._created_set.add(url_hash)
            self.created.append(url_hash)
            self._dirty = True

    def add_stats_done(self, url_hash):
        if url_hash not in self.stats_done:
            self.stats_done.add(url_hash)
            self._dirty = True

    def is_created(self, url_hash):
        return url_hash in self._created_set

    def flush(self):
        if not self._dirty:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = {"created": self.created, "stats_done": sorted(self.stats_done)}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)
        self._dirty = False


# --------------------------------------------------------------------------- #
# Buyruq
# --------------------------------------------------------------------------- #
class Command(BaseCommand):
    help = (
        "YouTube obunalarini CSV dan Channel jadvaliga import qiladi. "
        "Standart holat — dry-run (bazaga yozilmaydi)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="CSV fayl yo'li")
        parser.add_argument(
            "--dry-run", action=argparse.BooleanOptionalAction, default=True,
            help="Faqat hisobot (standart). Haqiqiy import uchun --no-dry-run.",
        )
        parser.add_argument("--limit", type=int, default=None, help="CSV dan faqat dastlabki N qator")
        parser.add_argument(
            "--stats", action="store_true",
            help="Import'dan keyin har bir yangi kanal uchun fetch_channel_stats() chaqiriladi",
        )
        parser.add_argument("--user", help="Kanallar egasi (username). Haqiqiy importda majburiy.")
        parser.add_argument("--state", help="Holat fayli yo'li (standart: <csv>.import-state.json)")
        parser.add_argument("--sleep-min", type=float, default=2.0, help="Statistika oralig'i, min soniya")
        parser.add_argument("--sleep-max", type=float, default=3.0, help="Statistika oralig'i, max soniya")
        parser.add_argument("--backup-dir", default="backups", help="Zaxira nusxa papkasi")
        parser.add_argument("--no-backup", action="store_true", help="Zaxira nusxa olmaslik (tavsiya etilmaydi)")

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        if opts["limit"] is not None and opts["limit"] < 1:
            raise CommandError("--limit 1 yoki undan katta bo'lishi kerak.")
        if opts["sleep_min"] < 0 or opts["sleep_max"] < opts["sleep_min"]:
            raise CommandError("--sleep-min/--sleep-max noto'g'ri.")

        csv_path = Path(opts["csv"])
        if not csv_path.is_file():
            raise CommandError(f"CSV topilmadi: {csv_path}")

        owner = None
        if not dry_run:
            if not opts["user"]:
                raise CommandError("Haqiqiy import uchun --user <username> kerak.")
            try:
                owner = get_user_model().objects.get(username=opts["user"])
            except get_user_model().DoesNotExist:
                raise CommandError(f"Foydalanuvchi topilmadi: {opts['user']}")

        rows = self._read_csv(csv_path, opts["limit"])
        state = ImportState(opts["state"] or f"{csv_path}.import-state.json")

        plan = self._analyze(rows)
        self._print_report(plan, dry_run, opts)

        stats_targets = self._stats_targets(plan, state) if opts["stats"] else []
        if opts["stats"]:
            self.stdout.write(f"  Statistika olinadigan kanallar: {len(stats_targets)}")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "DRY-RUN: bazaga hech narsa yozilmadi. Haqiqiy import: --no-dry-run --user <username>"
            ))
            return

        if not plan["new"] and not stats_targets:
            self.stdout.write("Qiladigan ish yo'q.")
            return

        if not opts["no_backup"]:
            backup_file = self._make_backup(opts["backup_dir"])
            self.stdout.write(f"Zaxira nusxa: {backup_file}")

        try:
            created, errors = self._create(plan["new"], owner, state)
            self.stdout.write(self.style.SUCCESS(f"Yaratildi: {created}, xato: {errors}"))
            if opts["stats"]:
                # yangi yaratilganlar ham qo'shilsin
                stats_targets = self._stats_targets(plan, state)
                self._fetch_stats(stats_targets, state, opts["sleep_min"], opts["sleep_max"])
        finally:
            state.flush()

    # ------------------------------------------------------------------ #
    def _read_csv(self, path, limit):
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV bo'sh yoki sarlavha qatori yo'q.")
            reader.fieldnames = [(name or "").strip().lower() for name in reader.fieldnames]
            if "channel_url" not in reader.fieldnames and "username" not in reader.fieldnames:
                raise CommandError("CSV da channel_url yoki username ustuni bo'lishi kerak.")
            rows = []
            for line_no, row in enumerate(reader, start=2):  # 1-qator — sarlavha
                if limit is not None and len(rows) >= limit:
                    break
                rows.append((line_no, row))
            return rows

    def _analyze(self, rows):
        """Qatorlarni toifalarga ajratadi: new / existing / csv_dup / invalid."""
        helper = Channel()
        db_hashes = set(Channel.objects.exclude(url_hash__isnull=True).values_list("url_hash", flat=True))
        # @handle katta-kichik harfga e'tiborsiz; url_hash esa aniq moslikni tekshiradi
        db_lower = {
            helper.normalize_url(u).lower()
            for u in Channel.objects.exclude(url__isnull=True).values_list("url", flat=True)
            if u
        }

        plan = {"total": len(rows), "new": [], "existing": [], "csv_dup": [], "invalid": [], "all_hashes": []}
        seen = set()
        for line_no, row in rows:
            data, error = parse_row(row)
            if error:
                plan["invalid"].append((line_no, error))
                continue
            url_hash = helper.generate_hash(data["url"])
            data["url_hash"] = url_hash
            key = data["url"].lower()
            if key in seen:
                plan["csv_dup"].append(line_no)
                continue
            seen.add(key)
            plan["all_hashes"].append(url_hash)
            if url_hash in db_hashes or key in db_lower:
                plan["existing"].append(line_no)
            else:
                plan["new"].append(data)
        return plan

    def _print_report(self, plan, dry_run, opts):
        mode = "DRY-RUN" if dry_run else "HAQIQIY IMPORT"
        self.stdout.write(self.style.MIGRATE_HEADING(f"=== import_subscriptions ({mode}) ==="))
        limit = f" (limit: {opts['limit']})" if opts["limit"] else ""
        self.stdout.write(f"  CSV qatorlari:        {plan['total']}{limit}")
        self.stdout.write(f"  Yangi:                {len(plan['new'])}")
        self.stdout.write(f"  Mavjud (o'tkazildi):  {len(plan['existing'])}")
        self.stdout.write(f"  CSV ichida dublikat:  {len(plan['csv_dup'])}")
        self.stdout.write(f"  Xato (noto'g'ri):     {len(plan['invalid'])}")
        for line_no, error in plan["invalid"][:20]:
            self.stdout.write(self.style.ERROR(f"    {line_no}-qator: {error}"))
        if len(plan["invalid"]) > 20:
            self.stdout.write(f"    ... yana {len(plan['invalid']) - 20} ta xato")

    def _stats_targets(self, plan, state):
        """Statistikasi hali olinmagan, SHU IMPORT yaratgan kanallar (CSV tartibida).

        Import'dan oldin bazada bo'lgan kanallarga tegilmaydi.
        """
        pending_new = {d["url_hash"] for d in plan["new"]}
        targets = []
        for url_hash in plan["all_hashes"]:
            if url_hash in state.stats_done:
                continue
            if url_hash in pending_new or state.is_created(url_hash):
                targets.append(url_hash)
        return targets

    # ------------------------------------------------------------------ #
    def _make_backup(self, backup_dir):
        from core.backup import _dump_all_data

        folder = Path(backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"savetube-backup-{datetime.now():%Y%m%d-%H%M%S}-import.json"
        data = _dump_all_data()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        return target

    def _create(self, new_rows, owner, state):
        created = errors = 0
        for index, data in enumerate(new_rows, start=1):
            try:
                with transaction.atomic():
                    channel = Channel(
                        user=owner,
                        url=data["url"],
                        title=data["title"],
                        description=data["description"],
                        subscriber_count=data["subscriber_count"],
                    )
                    quiet_save(channel)
                state.add_created(channel.url_hash)
                created += 1
            except Exception as exc:  # bitta qator butun importni to'xtatmasin
                errors += 1
                self.stderr.write(self.style.ERROR(f"  Yaratib bo'lmadi {data['url']}: {exc}"))
            if index % STATE_FLUSH_EVERY == 0:
                state.flush()
            if index % 100 == 0:
                self.stdout.write(f"  ... {index}/{len(new_rows)}")
        state.flush()
        return created, errors

    def _fetch_stats(self, targets, state, sleep_min, sleep_max):
        total = len(targets)
        ok = failed = 0
        for index, url_hash in enumerate(targets, start=1):
            channel = Channel.objects.filter(url_hash=url_hash).first()
            if channel is None:
                continue
            before = channel.subscriber_count
            try:
                channel.fetch_channel_stats()
                empty = not (channel.video_count or channel.shorts_count
                             or channel.live_count or channel.playlist_count)
                if empty and channel.subscriber_count == before:
                    # fetch_channel_stats() ichida xatolar yutiladi: bo'sh natija = ehtimol xato
                    raise RuntimeError("statistika olinmadi (bo'sh natija)")
                channel.subscriber_count = int(channel.subscriber_count or 0)
                quiet_save(channel)
                state.add_stats_done(url_hash)
                ok += 1
                self.stdout.write(
                    f"  [{index}/{total}] {channel.url} — {channel.subscriber_count} obunachi, "
                    f"{channel.video_count} video"
                )
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  [{index}/{total}] {channel.url}: {exc}"))
            if index % STATE_FLUSH_EVERY == 0:
                state.flush()
            if index < total:
                time.sleep(random.uniform(sleep_min, sleep_max))
        state.flush()
        self.stdout.write(self.style.SUCCESS(f"Statistika: {ok} ta muvaffaqiyatli, {failed} ta xato"))
        if failed:
            self.stdout.write("Xato bo'lganlar uchun buyruqni qayta ishga tushiring — qolganlari davom ettiriladi.")
