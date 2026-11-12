import csv
import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from youtube.management.commands.import_subscriptions import parse_row, parse_subs
from youtube.models import Channel

FIELDS = ["channel_id", "title", "username", "channel_url", "logo_url",
          "subs_display", "subs_count", "description"]


def by_url(url):
    """`url` maydoni shifrlangan (qidirib bo'lmaydi), shuning uchun url_hash orqali olamiz."""
    return Channel.objects.get(url_hash=Channel().generate_hash(url))


def make_row(handle, **extra):
    row = {
        "channel_id": "",
        "title": handle.title(),
        "username": f"@{handle}",
        "channel_url": f"https://www.youtube.com/@{handle}",
        "logo_url": "",
        "subs_display": "2.1K",
        "subs_count": "2100",
        "description": "Qisqa tavsif",
    }
    row.update(extra)
    return row


class ParseHelpersTests(TestCase):
    def test_parse_subs(self):
        self.assertEqual(parse_subs("2100", ""), 2100)
        self.assertEqual(parse_subs("1,234", ""), 1234)
        self.assertEqual(parse_subs("", "2.1K"), 2100)
        self.assertEqual(parse_subs("", "1.2M"), 1_200_000)
        self.assertEqual(parse_subs("", "3B subscribers"), 3_000_000_000)
        self.assertEqual(parse_subs("abc", "987"), 987)   # subs_count yaroqsiz -> display
        self.assertEqual(parse_subs("-5", ""), 0)          # manfiy qabul qilinmaydi
        self.assertEqual(parse_subs("", ""), 0)
        self.assertIsInstance(parse_subs("2100.0", ""), int)

    def test_parse_row_normalizes_url(self):
        data, error = parse_row(make_row("Ali", channel_url="http://youtube.com/@Ali/?si=x"))
        self.assertIsNone(error)
        self.assertEqual(data["url"], "https://www.youtube.com/@Ali")

    def test_parse_row_builds_url_from_username(self):
        data, error = parse_row(make_row("vali", channel_url=""))
        self.assertIsNone(error)
        self.assertEqual(data["url"], "https://www.youtube.com/@vali")

    def test_parse_row_invalid(self):
        for row in (
            make_row("x", channel_url="https://example.com/@x"),
            make_row("x", channel_url="not a url"),
            make_row("x", channel_url="", username="", channel_id=""),
        ):
            data, error = parse_row(row)
            self.assertIsNone(data)
            self.assertTrue(error)


class ImportSubscriptionsTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.user = get_user_model().objects.create_user("kai", password="x")

    # -- yordamchilar --------------------------------------------------- #
    def write_csv(self, rows, name="subs.csv"):
        path = self.dir / name
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def run_cmd(self, path, **kwargs):
        out, err = StringIO(), StringIO()
        kwargs.setdefault("sleep_min", 0)
        kwargs.setdefault("sleep_max", 0)
        call_command("import_subscriptions", csv=str(path), stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    def real(self, path, **kwargs):
        kwargs.setdefault("no_backup", True)
        return self.run_cmd(path, dry_run=False, user="kai", **kwargs)

    # -- dry-run -------------------------------------------------------- #
    def test_dry_run_is_default_and_writes_nothing(self):
        path = self.write_csv([make_row("ali"), make_row("vali")])
        out, _ = self.run_cmd(path)
        self.assertEqual(Channel.objects.count(), 0)
        self.assertIn("DRY-RUN", out)
        self.assertIn("Yangi:                2", out)
        self.assertFalse(Path(f"{path}.import-state.json").exists())

    def test_dry_run_reports_existing_invalid_and_csv_duplicates(self):
        existing = Channel(url="https://www.youtube.com/@bor", title="Bor", subscriber_count=1)
        existing.fetch_url_meta = lambda: None
        existing.fetch_channel_stats = lambda: None
        existing.save()
        path = self.write_csv([
            make_row("bor"),                       # mavjud
            make_row("yangi"),                     # yangi
            make_row("yangi"),                     # CSV ichida dublikat
            make_row("buzuq", channel_url="x", username=""),  # xato
        ])
        out, _ = self.run_cmd(path)
        self.assertIn("Yangi:                1", out)
        self.assertIn("Mavjud (o'tkazildi):  1", out)
        self.assertIn("CSV ichida dublikat:  1", out)
        self.assertIn("Xato (noto'g'ri):     1", out)
        self.assertIn("5-qator", out)  # buzuq qator CSV da 5-qator
        self.assertEqual(Channel.objects.count(), 1)

    # -- haqiqiy import ------------------------------------------------- #
    def test_import_creates_channels_without_network(self):
        path = self.write_csv([make_row("ali"), make_row("vali", subs_count="", subs_display="1.5M")])
        with mock.patch.object(Channel, "fetch_url_meta") as meta, \
                mock.patch.object(Channel, "fetch_channel_stats") as stats:
            self.real(path)
        meta.assert_not_called()
        stats.assert_not_called()
        self.assertEqual(Channel.objects.count(), 2)
        ali = by_url("https://www.youtube.com/@ali")
        self.assertEqual(ali.user, self.user)
        self.assertEqual(ali.subscriber_count, 2100)
        self.assertIsNotNone(ali.url_hash)
        self.assertIsNotNone(ali.checkout)
        self.assertEqual(by_url("https://www.youtube.com/@vali").subscriber_count, 1_500_000)

    def test_rerun_does_not_duplicate(self):
        path = self.write_csv([make_row("ali"), make_row("vali")])
        self.real(path)
        out, _ = self.real(path)
        self.assertEqual(Channel.objects.count(), 2)
        self.assertIn("Yangi:                0", out)
        self.assertIn("Mavjud (o'tkazildi):  2", out)

    def test_handle_case_difference_is_duplicate(self):
        path = self.write_csv([make_row("Ali")])
        self.real(path)
        path2 = self.write_csv([make_row("ali")], name="other.csv")
        self.real(path2)
        self.assertEqual(Channel.objects.count(), 1)

    def test_existing_records_untouched(self):
        existing = Channel(url="https://www.youtube.com/@bor", title="Eski nom",
                           description="Eski", subscriber_count=7, is_hidden=True)
        existing.fetch_url_meta = lambda: None
        existing.fetch_channel_stats = lambda: None
        existing.save()
        path = self.write_csv([make_row("bor", title="Yangi nom", subs_count="999")])
        self.real(path, stats=True)
        channel = Channel.objects.get()
        self.assertEqual(channel.title, "Eski nom")
        self.assertEqual(channel.subscriber_count, 7)
        self.assertTrue(channel.is_hidden)

    def test_invalid_rows_are_skipped_rest_imported(self):
        path = self.write_csv([
            make_row("ali"),
            make_row("buzuq", channel_url="https://example.com/x", username=""),
            make_row("vali"),
        ])
        self.real(path)
        self.assertEqual(Channel.objects.count(), 2)

    def test_limit(self):
        path = self.write_csv([make_row(f"kanal{i}") for i in range(5)])
        self.real(path, limit=3)
        self.assertEqual(Channel.objects.count(), 3)

    def test_real_import_requires_user(self):
        path = self.write_csv([make_row("ali")])
        with self.assertRaises(CommandError):
            self.run_cmd(path, dry_run=False, no_backup=True)
        with self.assertRaises(CommandError):
            self.run_cmd(path, dry_run=False, user="yoq-odam", no_backup=True)
        self.assertEqual(Channel.objects.count(), 0)

    def test_missing_csv_and_bad_header(self):
        with self.assertRaises(CommandError):
            self.run_cmd(self.dir / "yoq.csv")
        bad = self.dir / "bad.csv"
        bad.write_text("a,b\n1,2\n", encoding="utf-8")
        with self.assertRaises(CommandError):
            self.run_cmd(bad)

    def test_backup_made_before_real_import(self):
        path = self.write_csv([make_row("ali")])
        backup_dir = self.dir / "bk"
        with mock.patch("core.backup._dump_all_data", return_value="[]") as dump:
            self.run_cmd(path, dry_run=False, user="kai", backup_dir=str(backup_dir))
        dump.assert_called_once()
        self.assertEqual(len(list(backup_dir.glob("savetube-backup-*-import.json"))), 1)
        self.assertEqual(Channel.objects.count(), 1)

    def test_no_backup_in_dry_run(self):
        path = self.write_csv([make_row("ali")])
        with mock.patch("core.backup._dump_all_data") as dump:
            self.run_cmd(path, backup_dir=str(self.dir / "bk"))
        dump.assert_not_called()

    # -- statistika ----------------------------------------------------- #
    @staticmethod
    def fake_stats(fail_for=()):
        def _fetch(channel):
            if channel.url in fail_for:
                channel.video_count = 0   # fetch_channel_stats xatoni yutadi: bo'sh natija
                return
            channel.subscriber_count = 5_000_000
            channel.video_count = 10
        return _fetch

    def test_stats_updates_subscribers_and_counts(self):
        path = self.write_csv([make_row("ali")])
        with mock.patch.object(Channel, "fetch_channel_stats", self.fake_stats()):
            self.real(path, stats=True)
        channel = Channel.objects.get()
        self.assertEqual(channel.subscriber_count, 5_000_000)
        self.assertIsInstance(channel.subscriber_count, int)
        self.assertEqual(channel.video_count, 10)

    def test_stats_pause_between_channels(self):
        path = self.write_csv([make_row("a1"), make_row("a2"), make_row("a3")])
        with mock.patch.object(Channel, "fetch_channel_stats", self.fake_stats()), \
                mock.patch("youtube.management.commands.import_subscriptions.time.sleep") as sleep:
            self.real(path, stats=True, sleep_min=2, sleep_max=3)
        self.assertEqual(sleep.call_count, 2)  # 3 kanal -> 2 pauza
        for call in sleep.call_args_list:
            self.assertTrue(2 <= call.args[0] <= 3)

    def test_stats_error_is_logged_and_resumes_later(self):
        path = self.write_csv([make_row("a1"), make_row("a2"), make_row("a3")])
        bad = "https://www.youtube.com/@a2"

        with mock.patch.object(Channel, "fetch_channel_stats", self.fake_stats(fail_for=(bad,))):
            _, err = self.real(path, stats=True)
        self.assertIn(bad, err)  # xato log qilindi, jarayon davom etdi
        self.assertEqual(Channel.objects.filter(subscriber_count=5_000_000).count(), 2)

        state = json.loads(Path(f"{path}.import-state.json").read_text())
        self.assertEqual(len(state["created"]), 3)
        self.assertEqual(len(state["stats_done"]), 2)

        # Qayta ishga tushirish: faqat qolgan bitta kanal uchun statistika olinadi
        calls = []
        base = self.fake_stats()

        def tracking(channel):
            calls.append(channel.url)
            base(channel)

        with mock.patch.object(Channel, "fetch_channel_stats", tracking):
            out, _ = self.real(path, stats=True)
        self.assertEqual(calls, [bad])
        self.assertEqual(Channel.objects.count(), 3)
        self.assertEqual(Channel.objects.filter(subscriber_count=5_000_000).count(), 3)
        self.assertIn("Statistika olinadigan kanallar: 1", out)

    def test_stats_resume_after_crash_between_phases(self):
        """Import tugagan, statistika yarmida to'xtagan holat."""
        path = self.write_csv([make_row("a1"), make_row("a2")])
        self.real(path)  # --stats yo'q: faqat yaratiladi
        calls = []
        base = self.fake_stats()

        def tracking(channel):
            calls.append(channel.url)
            base(channel)

        with mock.patch.object(Channel, "fetch_channel_stats", tracking):
            self.real(path, stats=True)
        self.assertEqual(sorted(calls), ["https://www.youtube.com/@a1", "https://www.youtube.com/@a2"])
        self.assertEqual(Channel.objects.filter(video_count=10).count(), 2)

    def test_dry_run_with_stats_does_not_fetch(self):
        path = self.write_csv([make_row("ali")])
        with mock.patch.object(Channel, "fetch_channel_stats") as fetch:
            out, _ = self.run_cmd(path, stats=True)
        fetch.assert_not_called()
        self.assertIn("Statistika olinadigan kanallar: 1", out)
        self.assertEqual(Channel.objects.count(), 0)


class ChannelYoutubeLinkTests(TestCase):
    def setUp(self):
        from django.contrib import admin
        self.model_admin = admin.site._registry[Channel]

    def test_column_is_second_in_list_display(self):
        self.assertEqual(self.model_admin.list_display[1], "youtube_link")

    def test_link_opens_channel_in_new_tab(self):
        html = self.model_admin.youtube_link(Channel(url="https://www.youtube.com/@ali"))
        self.assertIn('href="https://www.youtube.com/@ali"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn("noopener", html)

    def test_unsafe_or_empty_url_has_no_link(self):
        self.assertEqual(self.model_admin.youtube_link(Channel(url="javascript:alert(1)")), "-")
        self.assertEqual(self.model_admin.youtube_link(Channel(url=None)), "-")
