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
from youtube.models import Channel, Video

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


class SubscriberGroupFilterTests(TestCase):
    def setUp(self):
        from django.contrib import admin
        from youtube.admin import SubscriberGroupFilter
        self.filter_cls = SubscriberGroupFilter
        self.model_admin = admin.site._registry[Channel]
        self.counts = {
            "a": 0, "b": 999, "c": 1_000, "d": 9_999, "e": 10_000, "f": 99_999,
            "g": 100_000, "h": 999_999, "i": 1_000_000, "j": 9_999_999,
            "k": 10_000_000, "l": 99_999_999, "m": 100_000_000, "n": 999_999_999,
            "o": 1_000_000_000, "p": 526_000_000_000 // 100,
        }
        for handle, count in self.counts.items():
            channel = Channel(url=f"https://www.youtube.com/@{handle}", title=handle, subscriber_count=count)
            channel.fetch_url_meta = lambda: None
            channel.fetch_channel_stats = lambda: None
            channel.save()

    def titles(self, group):
        from django.test import RequestFactory
        request = RequestFactory().get("/", {"subs_group": group} if group else {})
        flt = self.filter_cls(request, request.GET.copy(), Channel, self.model_admin)
        return sorted(flt.queryset(request, Channel.objects.all()).values_list("subscriber_count", flat=True))

    def test_filter_is_first_in_channel_list_filter(self):
        self.assertIs(self.model_admin.list_filter[0], self.filter_cls)

    def test_eight_groups_with_exact_boundaries(self):
        self.assertEqual(self.titles("g1"), [0, 999])
        self.assertEqual(self.titles("g2"), [1_000, 9_999])
        self.assertEqual(self.titles("g3"), [10_000, 99_999])
        self.assertEqual(self.titles("g4"), [100_000, 999_999])
        self.assertEqual(self.titles("g5"), [1_000_000, 9_999_999])
        self.assertEqual(self.titles("g6"), [10_000_000, 99_999_999])
        self.assertEqual(self.titles("g7"), [100_000_000, 999_999_999])
        self.assertEqual(self.titles("g8"), [1_000_000_000, 5_260_000_000])

    def test_groups_cover_every_channel_once(self):
        total = sum(len(self.titles(f"g{i}")) for i in range(1, 9))
        self.assertEqual(total, Channel.objects.count())

    def test_no_selection_returns_all(self):
        self.assertEqual(len(self.titles(None)), Channel.objects.count())


class VideoDurationGroupFilterTests(TestCase):
    def setUp(self):
        from django.contrib import admin
        from youtube.admin import DurationGroupFilter
        self.filter_cls = DurationGroupFilter
        self.model_admin = admin.site._registry[Video]
        self.seconds = [0, 1, 59, 60, 299, 300, 599, 600, 1_199, 1_200, 2_399, 2_400,
                        3_599, 3_600, 7_199, 7_200, 36_000]
        for index, value in enumerate(self.seconds):
            video = Video(url=f"https://www.youtube.com/watch?v=v{index:02d}", title=f"v{index}", duration=value)
            video.fetch_url_meta = lambda: None
            video.fetch_video_duration = lambda: None
            video.save()

    def durations(self, group):
        from django.test import RequestFactory
        request = RequestFactory().get("/", {"duration_group": group} if group else {})
        flt = self.filter_cls(request, request.GET.copy(), Video, self.model_admin)
        return sorted(flt.queryset(request, Video.objects.all()).values_list("duration", flat=True))

    def test_filter_is_first_in_video_list_filter(self):
        self.assertIs(self.model_admin.list_filter[0], self.filter_cls)

    def test_eight_groups_with_exact_boundaries(self):
        self.assertEqual(self.durations("g1"), [1, 59])
        self.assertEqual(self.durations("g2"), [60, 299])
        self.assertEqual(self.durations("g3"), [300, 599])
        self.assertEqual(self.durations("g4"), [600, 1_199])
        self.assertEqual(self.durations("g5"), [1_200, 2_399])
        self.assertEqual(self.durations("g6"), [2_400, 3_599])
        self.assertEqual(self.durations("g7"), [3_600, 7_199])
        self.assertEqual(self.durations("g8"), [7_200, 36_000])

    def test_unknown_duration_has_its_own_option(self):
        self.assertEqual(self.durations("unknown"), [0])

    def test_groups_and_unknown_cover_every_video_once(self):
        total = sum(len(self.durations(f"g{i}")) for i in range(1, 9)) + len(self.durations("unknown"))
        self.assertEqual(total, Video.objects.count())

    def test_no_choice_or_unknown_key_keeps_everything(self):
        self.assertEqual(len(self.durations(None)), Video.objects.count())
        self.assertEqual(len(self.durations("zzz")), Video.objects.count())


class ParseUrlsTests(TestCase):
    def test_splits_on_whitespace_commas_and_semicolons(self):
        from youtube.bulk_urls import parse_urls
        text = "https://youtu.be/a, https://youtu.be/b;https://youtu.be/c\nhttps://youtu.be/d  https://youtu.be/e"
        self.assertEqual(len(parse_urls(text)), 5)

    def test_drops_non_urls_and_duplicates_keeping_order(self):
        from youtube.bulk_urls import parse_urls
        text = "salom\nhttps://youtu.be/a\nhttps://youtu.be/A/\nhttps://youtu.be/b\nftp://x"
        self.assertEqual(parse_urls(text), ["https://youtu.be/a", "https://youtu.be/b"])

    def test_empty_input(self):
        from youtube.bulk_urls import parse_urls
        self.assertEqual(parse_urls(""), [])
        self.assertEqual(parse_urls(None), [])


class VideoBulkAddTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser("bulk", "bulk@example.com", "pw")
        self.client.force_login(user)
        patches = [
            mock.patch.object(Video, "fetch_url_meta", lambda self: None),
            mock.patch.object(Video, "fetch_video_duration", lambda self: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        # Admin so'rovi "joriy foydalanuvchi"ni thread-local'da qoldiradi; keyingi testlarga o'tmasin.
        from shared.utils import middleware
        self.addCleanup(lambda: setattr(middleware._thread_locals, "user", None))

    def add(self, urls):
        return self.client.post("/admin/youtube/video/add/", {"url": urls, "status": "new", "start_from": 0, "_save": "Saqlash"}, follow=True)

    def video_count(self):
        return Video.objects.count()

    def test_add_page_uses_a_textarea_for_urls(self):
        response = self.client.get("/admin/youtube/video/add/")
        self.assertContains(response, "<textarea")
        self.assertContains(response, "Har bir qatorga bitta havola")

    def test_several_urls_create_one_video_each(self):
        self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb\nhttps://www.youtube.com/watch?v=ccccccccccc")
        self.assertEqual(self.video_count(), 3)

    def test_single_url_still_works(self):
        self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.assertEqual(self.video_count(), 1)

    def test_existing_urls_are_skipped_not_duplicated(self):
        self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb")
        self.assertEqual(self.video_count(), 2)

    def test_all_existing_urls_are_refused(self):
        self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb")
        response = self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb")
        self.assertContains(response, "allaqachon mavjud")
        self.assertEqual(self.video_count(), 2)

    def test_edit_page_keeps_a_single_line_url_field(self):
        self.add("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        video = Video.objects.get()
        response = self.client.get(f"/admin/youtube/video/{video.pk}/change/")
        self.assertNotContains(response, "Har bir qatorga bitta havola")
