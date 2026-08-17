from django.db import models
from django.conf import settings
from django_extensions.db.models import TimeStampedModel
from django.forms.models import model_to_dict
from django.utils.translation import gettext_lazy as _
import hashlib
from shared.utils.fields import EncryptedTextField, EncryptedCharField


# =====================================================
# 🔍 AUTO ENCRYPT + HASH MIXIN
# =====================================================
class AutoEncryptHashMixin:
    HASH_FIELDS = []  # agar kerak bo'lsa, url va shunga o'xshash fieldlar

    def generate_hash(self, value):
        return hashlib.sha256(value.encode()).hexdigest()

    def normalize_url(self, value):
        if not value:
            return value
        import re
        value = re.sub(r'^https?://m\.youtube\.com', 'https://www.youtube.com', value)
        value = value.rstrip('/')
        if '/@' in value or '/channel/' in value:
            value = value.split('?')[0]
        return value

    def clean(self):
        from django.core.exceptions import ValidationError
        if hasattr(super(), 'clean'):
            super().clean()
            
        errors = {}
        for field in self.HASH_FIELDS:
            value = getattr(self, field, None)
            if value:
                if field == 'url':
                    value = self.normalize_url(value)
                    setattr(self, field, value)
                hash_val = self.generate_hash(value)
                qs = self.__class__.objects.filter(**{f"{field}_hash": hash_val})
                if self.pk:
                    qs = qs.exclude(pk=self.pk)
                if qs.exists():
                    errors[field] = f"Bunday {field} bazada allaqachon mavjud."
                    
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # 1️⃣ Hash yaratish
        for field in self.HASH_FIELDS:
            value = getattr(self, field, None)
            if value:
                if field == 'url':
                    value = self.normalize_url(value)
                    setattr(self, field, value)
                setattr(self, f"{field}_hash", self.generate_hash(value))
            else:
                setattr(self, f"{field}_hash", None)

        # 2️⃣ Char/Text fieldlarni encrypt qilish (EncryptedTextField ishlaydi)
        for field in self._meta.get_fields():
            if isinstance(field, (models.CharField, models.TextField)) and hasattr(self, field.name):
                val = getattr(self, field.name)
                if val is not None:
                    setattr(self, field.name, val)  # Encrypted field auto-encrypt qiladi

        super().save(*args, **kwargs)


# =====================================================
# 🔗 URL METADATA + STATS FETCH MIXIN
# =====================================================
class AutoFetchUrlMetaMixin:
    """URL kiritilganda title, description va statistika avtomatik olinadi."""

    VIDEOS_PAGE_CAP = 40
    PLAYLISTS_PAGE_CAP = 30
    INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

    @classmethod
    def _http_get(cls, url, timeout=10):
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="replace")

    @classmethod
    def _yt_json(cls, html):
        import json
        marker = "var ytInitialData = "
        i = html.find(marker)
        if i < 0:
            return {}
        start = i + len(marker)
        depth, quote, escaped = 0, None, False
        for j in range(start, len(html)):
            c = html[j]
            if quote:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:j + 1])
                    except Exception:
                        return {}
        return {}

    @classmethod
    def _count_lockups(cls, obj, expected_type=None):
        n = 0
        if isinstance(obj, dict):
            if "lockupViewModel" in obj:
                if expected_type is None or obj["lockupViewModel"].get("contentType") == expected_type:
                    n += 1
            for v in obj.values():
                n += cls._count_lockups(v, expected_type)
        elif isinstance(obj, list):
            for v in obj:
                n += cls._count_lockups(v, expected_type)
        return n

    @classmethod
    def _find_continuation_token(cls, obj):
        if isinstance(obj, dict):
            item = obj.get("continuationItemRenderer")
            if item:
                try:
                    return item["continuationEndpoint"]["continuationCommand"]["token"]
                except Exception:
                    return None
            for v in obj.values():
                token = cls._find_continuation_token(v)
                if token:
                    return token
        elif isinstance(obj, list):
            for v in obj:
                token = cls._find_continuation_token(v)
                if token:
                    return token
        return None

    @classmethod
    def _parse_count_text(cls, text):
        """'510K subscribers' / '9,4 ming obunachi' -> int"""
        import re
        if not text:
            return None
        m = re.search(r"([\d.,]+)\s*([KMB]|ming|million|milliard)?", text, re.IGNORECASE)
        if not m:
            return None
        num = float(m.group(1).replace(",", ""))
        suffix = (m.group(2) or "").lower()
        mult = {"k": 1000, "m": 1000000, "b": 1000000000,
                "ming": 1000, "million": 1000000, "milliard": 1000000000}.get(suffix, 1)
        return int(num * mult)

    @classmethod
    def _enumerate_tab(cls, base_url, cap, expected_type=None):
        """Tab sahifalarini continuation orqali aylanib, yozuvlar sonini qaytaradi."""
        import json
        import urllib.request
        try:
            html = cls._http_get(base_url)
            data = cls._yt_json(html)
            if not data:
                return None
            total = cls._count_lockups(data, expected_type)
            token = cls._find_continuation_token(data)
            pages = 1
            while token and pages < cap:
                body = json.dumps({
                    "context": {"client": {"clientName": "WEB", "clientVersion": "2.20250101.00.00", "hl": "en"}},
                    "continuation": token,
                }).encode()
                req = urllib.request.Request(
                    "https://www.youtube.com/youtubei/v1/browse?key=" + cls.INNERTUBE_KEY,
                    data=body,
                    headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                )
                cont = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="replace"))
                pages += 1
                total += cls._count_lockups(cont, expected_type)
                token = cls._find_continuation_token(cont)
            return total
        except Exception:
            return None

    def fetch_url_meta(self):
        import html as html_module
        import re

        url = getattr(self, "url", None)
        if not url:
            return
        # Ikkalasi ham bo'lsa va title xato bo'lmasa, hamda duration kerak bo'lmasa — fetch shart emas
        current_title = getattr(self, "title", None)
        has_valid_title = current_title and current_title not in ["- YouTube", "YouTube"]
        has_description = bool(getattr(self, "description", None))
        
        needs_duration = hasattr(self, "duration") and not getattr(self, "duration")
        
        if has_valid_title and has_description and not needs_duration:
            return

        # Noto'g'ri title'larni tozalash
        if current_title in ["- YouTube", "YouTube"]:
            self.title = None

        try:
            if "youtube.com" in url or "youtu.be" in url:
                # YouTube URL'lari uchun yt-dlp dan foydalanamiz, chunki HTTP GET
                # ko'pincha 'consent' yoki cookie so'rab, noto'g'ri HTML qaytaradi.
                import yt_dlp
                opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 12}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                
                if not getattr(self, "title", None):
                    t = info.get("title")
                    if t:
                        self.title = t.strip()[:255]
                        
                if not getattr(self, "description", None):
                    d = info.get("description")
                    if d:
                        self.description = d
                        
                if hasattr(self, "duration") and not getattr(self, "duration"):
                    dur = info.get("duration")
                    if dur:
                        self.duration = int(dur)
            else:
                html_content = self._http_get(url, timeout=8)
                # Boshqa saytlar uchun oddiy HTML meta
                if not getattr(self, "title", None):
                    m = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
                    if m:
                        t = html_module.unescape(m.group(1)).strip()
                        if t:
                            self.title = t[:255]

                if not getattr(self, "description", None):
                    m = re.search(
                        r'<meta[^>]*(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\'](.*?)["\']',
                        html_content, re.IGNORECASE
                    )
                    if m:
                        self.description = html_module.unescape(m.group(1).strip())
        except Exception:
            pass

    @classmethod
    def _find_key(cls, obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = cls._find_key(v, key)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = cls._find_key(v, key)
                if r:
                    return r
        return None

    @classmethod
    def _metadata_rows(cls, obj):
        """Yangi UI metadata qatorlaridagi matnlarni yig'adi. Masalan '164K subscribers', '6.1K videos'."""
        texts = []
        if isinstance(obj, dict):
            parts = obj.get("metadataParts")
            if isinstance(parts, list):
                for p in parts:
                    content = ((p.get("text") or {}).get("content") or
                               ((p.get("text") or {}).get("content")) or "")
                    if content:
                        texts.append(content)
            for v in obj.values():
                texts.extend(cls._metadata_rows(v))
        elif isinstance(obj, list):
            for v in obj:
                texts.extend(cls._metadata_rows(v))
        return texts

    @classmethod
    def _ydl_cookiefile(cls):
        """YouTubeConfig'dagi cookie'larni vaqtincha faylga yozib, path qaytaradi."""
        import os, tempfile
        try:
            cfg = YouTubeConfig.objects.get(pk=1)
        except YouTubeConfig.DoesNotExist:
            return None
        if not cfg.enabled or not cfg.cookies:
            return None
        fd, path = tempfile.mkstemp(prefix="yt_cookies_", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(cfg.cookies)
        return path

    def fetch_channel_stats(self):
        """Kanal statistikasi: obunachilar, videolar, pleylistlar soni.

        - Obunachilar: yt-dlp channel_follower_count (asosiy, tez va aniq).
        - Videolar soni: kanal /videos sahifasidagi metadata qatori ('6.1K videos').
          YouTube A/B variant berganida (eski cache) yt-dlp to'liq sanash rezerv, biroq
          yirik kanallarda u juda sekin -> shuning uchun meta qatoriga ustun beramiz.
        - Pleylistlar soni: /playlists sahifasini continuation orqali sanash.
        """
        import re, os
        url = getattr(self, "url", None)
        if not url:
            return
        base_url = url.rstrip("/")
        cookiefile = self._ydl_cookiefile()

        # 1) Obunachilar: yt-dlp (playlistend=0 -> pleylistni to'liq o'qimaydi, tez)
        subscribers = None
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True, "socket_timeout": 12, "playlistend": 0}
            if cookiefile:
                opts["cookiefile"] = cookiefile
            with yt_dlp.YoutubeDL(opts) as ydl:
                ch = ydl.extract_info(base_url, download=False)
            subscribers = ch.get("channel_follower_count")
        except Exception:
            pass
        if subscribers:
            self.subscriber_count = subscribers

        # 2) Videolar soni: metadata qatori ('6.1K videos')
        videos = None
        try:
            html_v = self._http_get(base_url + "/videos", timeout=10)
            texts = self._metadata_rows(self._yt_json(html_v))
            for t in texts:
                if videos is None and re.search(r"([\d.,]+)\s*([KMB]?)\s*videos?", t, re.IGNORECASE):
                    videos = self._parse_count_text(t)
                    break
        except Exception:
            pass

        # 3) Rezerv: yt-dlp to'liq enumeration (yirik kanallarda sekin; faqat meta bermasa)
        if not videos:
            try:
                import yt_dlp
                opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                        "skip_download": True, "socket_timeout": 12}
                if cookiefile:
                    opts["cookiefile"] = cookiefile
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(base_url + "/videos", download=False)
                videos = len(info.get("entries") or []) or info.get("playlist_count")
            except Exception:
                videos = 0

        self.video_count = videos or 0

        # Shorts soni
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True, "socket_timeout": 12}
            if cookiefile:
                opts["cookiefile"] = cookiefile
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(base_url + "/shorts", download=False)
            self.shorts_count = len(info.get("entries") or [])
        except Exception:
            self.shorts_count = 0

        # Live streams soni
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True, "socket_timeout": 12}
            if cookiefile:
                opts["cookiefile"] = cookiefile
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(base_url + "/streams", download=False)
            self.live_count = len(info.get("entries") or [])
        except Exception:
            self.live_count = 0

        self.video_count = max(0, self.video_count - self.shorts_count - self.live_count)

        # 4) Pleylistlar soni
        playlists_total = self._enumerate_tab(base_url + "/playlists", self.PLAYLISTS_PAGE_CAP, expected_type="LOCKUP_CONTENT_TYPE_PLAYLIST")
        if playlists_total is not None:
            self.playlist_count = playlists_total

        if cookiefile:
            try:
                os.remove(cookiefile)
            except OSError:
                pass

    def fetch_playlist_stats(self):
        """Pleylistdagi videolar soni va umumiy davomiyligi."""
        url = getattr(self, "url", None)
        if not url:
            return
        try:
            html_content = self._http_get(url, timeout=8)
            data = self._yt_json(html_content)
            found = self._find_num_videos(data)
            if found is not None:
                self.video_count = found
        except Exception:
            pass

        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "socket_timeout": 12}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = info.get("entries") or []
            total_duration = sum(entry.get("duration") or 0 for entry in entries)
            self.duration = int(total_duration)
            if not self.video_count and entries:
                self.video_count = len(entries)
        except Exception:
            pass

    @classmethod
    def _find_num_videos(cls, obj):
        import re
        if isinstance(obj, dict):
            nvt = obj.get("numVideosText")
            if isinstance(nvt, dict):
                runs = nvt.get("runs") or []
                text = "".join(r.get("text", "") for r in runs)
                m = re.search(r"([\d.,]+)", text)
                if m:
                    try:
                        return int(float(m.group(1).replace(",", "")))
                    except ValueError:
                        return None
            for v in obj.values():
                r = cls._find_num_videos(v)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = cls._find_num_videos(v)
                if r is not None:
                    return r
        return None

    def fetch_video_duration(self):
        """Video davomiyligi (soniyalarda)."""
        import re
        url = getattr(self, "url", None)
        if not url:
            return
        try:
            html_content = self._http_get(url, timeout=8)
            m = re.search(r'"lengthSeconds":"(\d+)"', html_content)
            if m:
                self.duration = int(m.group(1))
                return
            m = re.search(r'"approxDurationMs":"(\d+)"', html_content)
            if m:
                self.duration = int(m.group(1)) // 1000
        except Exception:
            pass

    def fetch_realtime_stats(self):
        """Video stats (views, likes, channel, logo, subs, date) ni yt-dlp bilan
        bitta so'rovda olish + Redis'ga 1 kunga keshlash."""
        from django.core.cache import cache
        import yt_dlp

        cache_key = f"yt_realtime:video:{self.pk}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

        url = getattr(self, "url", None)
        if not url:
            return None

        opts = {
            'quiet': True,
            'skip_download': True,
            'getcomments': True,
            'cookiefile': self._ydl_cookiefile(),
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            # Upload date formatting: 20250422 -> "22 Aprel 2025"
            upload_date_raw = info.get("upload_date", "")
            upload_date_fmt = ""
            if upload_date_raw and len(upload_date_raw) == 8:
                months_uz = {
                    "01": "Yanvar", "02": "Fevral", "03": "Mart",
                    "04": "Aprel", "05": "May", "06": "Iyun",
                    "07": "Iyul", "08": "Avgust", "09": "Sentyabr",
                    "10": "Oktyabr", "11": "Noyabr", "12": "Dekabr",
                }
                y, m, d = upload_date_raw[:4], upload_date_raw[4:6], upload_date_raw[6:8]
                upload_date_fmt = f"{int(d)} {months_uz.get(m, m)} {y}"

            # Channel avatar: use YouTube's default channel avatar URL
            channel_id = info.get("channel_id", "")
            channel_logo = ""
            if channel_id:
                channel_logo = f"https://yt3.googleusercontent.com/channel/{channel_id}"

            # Subscriber count formatting
            subs_raw = info.get("channel_follower_count", 0) or 0
            if subs_raw >= 1_000_000:
                subs_fmt = f"{subs_raw / 1_000_000:.1f}M"
            elif subs_raw >= 1_000:
                subs_fmt = f"{subs_raw / 1_000:.1f}K"
            else:
                subs_fmt = str(subs_raw)

            # View count formatting
            views_raw = info.get("view_count", 0) or 0
            if views_raw >= 1_000_000:
                views_fmt = f"{views_raw / 1_000_000:.1f}M"
            elif views_raw >= 1_000:
                views_fmt = f"{views_raw / 1_000:.1f}K"
            else:
                views_fmt = str(views_raw)

            # Comments parsing (max 20)
            raw_comments = info.get("comments", []) or []
            comments = []
            for c in raw_comments[:20]:
                comments.append({
                    "author": c.get("author", "Foydalanuvchi"),
                    "text": c.get("text", ""),
                    "like_count": c.get("like_count", 0)
                })

            stats = {
                "title": info.get("title", ""),
                "view_count": views_raw,
                "view_count_fmt": views_fmt,
                "like_count": info.get("like_count", 0) or 0,
                "uploader": info.get("uploader", ""),
                "uploader_id": info.get("uploader_id", ""),
                "channel_url": info.get("channel_url", ""),
                "channel_logo": channel_logo,
                "subscriber_count": subs_raw,
                "subscriber_count_fmt": subs_fmt,
                "upload_date": upload_date_fmt,
                "upload_date_raw": upload_date_raw,
                "duration": info.get("duration", 0),
                "thumbnail": info.get("thumbnail", ""),
                "description": info.get("description", ""),
                "tags": info.get("tags", []) or [],
                "comments": comments,
                "comment_count": info.get("comment_count", len(comments)),
            }
            # Cache for 1 day
            cache.set(cache_key, stats, timeout=86400)
            return stats
        except Exception:
            return None


# =====================================================
# 📜 AUDIT LOG
# =====================================================
class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("create", _("Yaratish")),
        ("update", _("Yangilash")),
        ("delete", _("O'chirish")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("Foydalanuvchi")
    )

    model = models.CharField(_("Model nomi"), max_length=100)
    object_id = models.CharField(_("Obyekt ID"), max_length=100)
    action = models.CharField(_("Amal"), max_length=10, choices=ACTION_CHOICES)
    changes = models.JSONField(_("O'zgarishlar"), null=True, blank=True)
    created_at = models.DateTimeField(_("Yaratilgan vaqt"), auto_now_add=True)

    class Meta:
        verbose_name = _("Audit Jurnali")
        verbose_name_plural = _("Audit Jurnallari")

    def __str__(self):
        return f"{self.model} ({self.object_id}) - {self.action}"


# =====================================================
# 📜 AUDIT MIXIN
# =====================================================
class AuditMixin:

    def get_model_name(self):
        return self.__class__.__name__

    def json_safe(self, value):
        import datetime
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: self.json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.json_safe(v) for v in value]
        return value

    def get_changes(self, old, new):
        changes = {}
        for field, old_value in old.items():
            new_value = new.get(field)
            if old_value != new_value:
                changes[field] = {"old": self.json_safe(old_value), "new": self.json_safe(new_value)}
        return changes

    def save(self, *args, **kwargs):
        from shared.utils.middleware import get_current_user
        user = get_current_user()

        if self.pk:
            old = self.__class__.objects.get(pk=self.pk)
            old_data = model_to_dict(old)
            super().save(*args, **kwargs)
            new_data = model_to_dict(self)

            changes = self.get_changes(old_data, new_data)

            if changes:
                AuditLog.objects.create(
                    user=user,
                    model=self.get_model_name(),
                    object_id=self.pk,
                    action="update",
                    changes=changes
                )
        else:
            super().save(*args, **kwargs)
            AuditLog.objects.create(
                user=user,
                model=self.get_model_name(),
                object_id=self.pk,
                action="create",
                changes=self.json_safe(model_to_dict(self))
            )

    def delete(self, *args, **kwargs):
        from shared.utils.middleware import get_current_user
        user = get_current_user()

        AuditLog.objects.create(
            user=user,
            model=self.get_model_name(),
            object_id=self.pk,
            action="delete",
            changes=self.json_safe(model_to_dict(self))
        )

        super().delete(*args, **kwargs)


# =====================================================
# 📦 MODELS
# =====================================================
class Category(AuditMixin, TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))
    name = models.CharField(_("Nomi"), max_length=100)
    priority = models.ForeignKey('Priority', null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Muhimligi"))

    class Meta:
        verbose_name = _("Kategoriya")
        verbose_name_plural = _("Kategoriyalar")

    def __str__(self):
        return self.name or ""


class Channel(AuditMixin, AutoEncryptHashMixin, AutoFetchUrlMetaMixin, TimeStampedModel):
    HASH_FIELDS = ["url"]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))

    url = EncryptedTextField(_("Kanal havolasi"), unique=True, null=True, blank=True)
    url_hash = models.CharField(_("Havola xeshi"), max_length=64, db_index=True, unique=True, null=True, blank=True)

    title = EncryptedCharField(_("Sarlavha"), max_length=255, null=True, blank=True)
    description = EncryptedTextField(_("Tavsif"), null=True, blank=True)

    total_watch = models.PositiveSmallIntegerField(_("Ko'rilgan videolar"), default=0)
    subscriber_count = models.BigIntegerField(_("Obunachilar soni"), default=0)
    video_count = models.PositiveIntegerField(_("Videolar soni"), default=0)
    shorts_count = models.PositiveIntegerField(_("Shorts soni"), default=0)
    live_count = models.PositiveIntegerField(_("Jonli efirlar soni"), default=0)
    playlist_count = models.PositiveIntegerField(_("Pleylistlar soni"), default=0)
    next_video = models.CharField(_("Keyingi video"), max_length=255, null=True, blank=True)
    has_new_video = models.BooleanField(_("Yangi video bormi?"), default=False)
    is_hidden = models.BooleanField(_("Yashirish"), default=False)
    is_archived = models.BooleanField(_("Arxivlash"), default=False)

    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Kategoriya"))
    tags = models.ManyToManyField('youtube.Label', blank=True, verbose_name=_("Teglar"))

    checkout = models.DateTimeField(_("Tekshirish vaqti"), db_index=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        import datetime
        from django.utils import timezone
        
        # Avtomatik checkout o'rnatish (mahalliy vaqt bo'yicha)
        if not self.checkout:
            now_local = timezone.now()
            tomorrow_local = now_local + datetime.timedelta(days=1)
            next_day = tomorrow_local.replace(hour=8, minute=0, second=0, microsecond=0)
            # Agar ertaga yakshanba bo'lsa — dushanbaga sur
            if next_day.weekday() == 6:
                next_day = next_day + datetime.timedelta(days=1)
            self.checkout = next_day

        # URL dan title va description avtomatik fetch
        self.fetch_url_meta()

        # Statistika (faqat bo'sh bo'lganlari): obunachilar, videolar, pleylistlar
        if not (self.subscriber_count or self.video_count or self.playlist_count):
            self.fetch_channel_stats()

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Kanal")
        verbose_name_plural = _("Kanallar")

    def __str__(self):
        return self.title or self.url


class Priority(AuditMixin, TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))
    name = models.CharField(_("Muhimlik darajasi"), max_length=100)

    class Meta:
        verbose_name = _("Muhimlik")
        verbose_name_plural = _("Muhimlik darajalari")

    def __str__(self):
        return self.name or ""


class Label(AuditMixin, TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))
    name = models.CharField(_("Teg nomi"), max_length=100)

    class Meta:
        verbose_name = _("Teg")
        verbose_name_plural = _("Teglar")

    def __str__(self):
        return self.name or ""


class Reminder(AuditMixin, TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))
    time = models.DurationField(_("Eslatma vaqti"))

    class Meta:
        verbose_name = _("Eslatma")
        verbose_name_plural = _("Eslatmalar")

    def __str__(self):
        return str(self.time)


class Video(AuditMixin, AutoEncryptHashMixin, AutoFetchUrlMetaMixin, TimeStampedModel):
    HASH_FIELDS = ["url"]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))

    url = EncryptedTextField(_("Havola (URL)"), unique=True, null=True, blank=True)
    url_hash = models.CharField(_("Havola xeshi"), max_length=64, db_index=True, unique=True, null=True, blank=True)

    title = EncryptedCharField(_("Sarlavha"), max_length=255, null=True, blank=True)
    description = EncryptedTextField(_("Tavsif"), null=True, blank=True)

    start_from = models.PositiveSmallIntegerField(_("Shu vaqtdan boshlash (sek)"), default=0)
    duration = models.PositiveIntegerField(_("Davomiyligi (soniya)"), default=0)

    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Kategoriya"))
    priority = models.ForeignKey(Priority, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Muhimligi"))

    tags = models.ManyToManyField(Label, blank=True, verbose_name=_("Teglar"))
    channels = models.ManyToManyField(Channel, blank=True, verbose_name=_("Kanallar"))

    checkout = models.DateTimeField(_("Tekshirish vaqti"), db_index=True, null=True, blank=True)
    deadline = models.DateTimeField(_("Muddati (Deadline)"), db_index=True, null=True, blank=True)
    reminders = models.ManyToManyField(Reminder, blank=True, verbose_name=_("Eslatmalar"))

    STATUS_CHOICES = [
        ("new", _("Yangi")),
        ("watched", _("Ko'rilgan")),
        ("skipped", _("O'tkazib yuborildi")),
        ("archived", _("Arxivlangan")),
    ]
    status = models.CharField(_("Holati"), max_length=20, choices=STATUS_CHOICES, default="new")

    is_hidden = models.BooleanField(_("Yashirish"), default=False)
    is_live = models.BooleanField(_("Jonli efir (Live)"), default=False)

    class Meta:
        verbose_name = _("Video")
        verbose_name_plural = _("Videolar")
        constraints = [
            models.UniqueConstraint(fields=["user", "url_hash"], name="unique_user_video")
        ]

    def __str__(self):
        return self.title or self.url

    @property
    def duration_display(self):
        """Davomiylikni o'zbek tilida tabiiy formatda ko'rsatadi."""
        s = self.duration or 0
        if s == 0:
            return "-"
        d, rem = divmod(s, 86400)
        h, rem = divmod(rem, 3600)
        m, sec = divmod(rem, 60)

        parts = []
        if d > 0:
            parts.append(f"{d} kun")
        if h > 0:
            parts.append(f"{h:02d} soat")
        if m > 0 or h > 0 or d > 0:
            parts.append(f"{m:02d} daqiqa")
        parts.append(f"{sec:02d} soniya")
        return " ".join(parts)

    def save(self, *args, **kwargs):
        import datetime
        from django.utils import timezone

        if not self.checkout:
            now_local = timezone.now()
            tomorrow_local = now_local + datetime.timedelta(days=1)
            next_day = tomorrow_local.replace(hour=8, minute=0, second=0, microsecond=0)
            # Agar ertaga yakshanba bo'lsa — dushanbaga sur
            if next_day.weekday() == 6:
                next_day = next_day + datetime.timedelta(days=1)
            self.checkout = next_day

        # URL dan title, description va duration avtomatik fetch
        self.fetch_url_meta()
        if not self.duration:
            self.fetch_video_duration()

        # Prioritet bo'sh qolsa, Kategoriyadan oladi
        if self.category and self.category.priority and not self.priority:
            self.priority = self.category.priority

        super().save(*args, **kwargs)


class Playlist(AuditMixin, AutoEncryptHashMixin, AutoFetchUrlMetaMixin, TimeStampedModel):
    HASH_FIELDS = ["url"]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Foydalanuvchi"))

    url = EncryptedTextField(_("Pleylist havolasi"), unique=True, null=True, blank=True)
    url_hash = models.CharField(_("Havola xeshi"), max_length=64, db_index=True, unique=True, null=True, blank=True)

    title = EncryptedCharField(_("Sarlavha"), max_length=255, null=True, blank=True)
    description = EncryptedTextField(_("Tavsif"), null=True, blank=True)
    video_count = models.PositiveIntegerField(_("Videolar soni"), default=0)
    duration = models.PositiveIntegerField(_("Davomiyligi (soniya)"), default=0)
    next_video = models.CharField(_("Keyingi video"), max_length=255, null=True, blank=True)

    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Kategoriya"))
    channel = models.ForeignKey(Channel, null=True, blank=True, on_delete=models.SET_NULL, verbose_name=_("Kanal"))
    tags = models.ManyToManyField('youtube.Label', blank=True, verbose_name=_("Teglar"))

    is_hidden = models.BooleanField(_("Yashirish"), default=False)

    checkout = models.DateTimeField(_("Tekshirish vaqti"), null=True, blank=True)

    def __str__(self):
        return self.title or self.url or ""

    @property
    def duration_display(self):
        """Davomiylikni o'zbek tilida tabiiy formatda ko'rsatadi."""
        s = self.duration or 0
        if s == 0:
            return "-"
        d, rem = divmod(s, 86400)
        h, rem = divmod(rem, 3600)
        m, sec = divmod(rem, 60)

        parts = []
        if d > 0:
            parts.append(f"{d} kun")
        if h > 0:
            parts.append(f"{h:02d} soat")
        if m > 0 or h > 0 or d > 0:
            parts.append(f"{m:02d} daqiqa")
        parts.append(f"{sec:02d} soniya")
        return " ".join(parts)

    def save(self, *args, **kwargs):
        import datetime
        from django.utils import timezone

        if not self.checkout:
            now_local = timezone.now()
            tomorrow_local = now_local + datetime.timedelta(days=1)
            next_day = tomorrow_local.replace(hour=8, minute=0, second=0, microsecond=0)
            # Agar ertaga yakshanba bo'lsa — dushanbaga sur
            if next_day.weekday() == 6:
                next_day = next_day + datetime.timedelta(days=1)
            self.checkout = next_day

        # URL dan title va description avtomatik fetch
        self.fetch_url_meta()

        # Pleylistdagi videolar soni (faqat bo'lmasa)
        if not self.video_count:
            self.fetch_playlist_stats()

        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Pleylist")
        verbose_name_plural = _("Pleylistlar")

    def __str__(self):
        return self.title or self.url


# =====================================================
# 🍪 YOUTUBE COOKIE CONFIG (singleton)
# =====================================================
class YouTubeConfig(models.Model):
    """YouTube cookie'lari (netscape/cookies.txt formati) — yt-dlp'ga cookies fayl sifatida beriladi.

    YouTube cache/limit tufayli aniq stats bermayotganda, brauzerdan eksport qilingan
    cookie'lar kerak. Faqat bitta yozuv saqlanadi (singleton).
    """

    enabled = models.BooleanField(_("Cookie'lar ishlatilsinmi?"), default=False)
    cookies = models.TextField(
        _("cookie.txt (netscape formati)"),
        blank=True,
        help_text=_("Brauzer cookie'larini netscape formatda eksport qilib shu yerga yopishtiring"),
    )
    updated_at = models.DateTimeField(_("Yangilangan vaqt"), auto_now=True)

    class Meta:
        verbose_name = _("YouTube Cookie sozlamasi")
        verbose_name_plural = _("YouTube Cookie sozlamalari")

    def __str__(self):
        return _("YouTube Cookie sozlamasi")

    def save(self, *args, **kwargs):
        # Singleton: faqat bitta yozuv bo'ladi
        self.pk = 1
        super().save(*args, **kwargs)
