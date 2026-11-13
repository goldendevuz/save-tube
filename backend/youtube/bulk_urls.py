"""Bir nechta havolani birdaniga kiritish (admin "Qo'shish" sahifasi uchun)."""
import re

URL_SPLIT = re.compile(r"[\s,;]+")

# Qo'shimcha obyektlarga formadan ko'chiriladigan oddiy maydonlar va M2M maydonlar
COPIED_FIELDS = ("category", "priority", "start_from", "status", "is_hidden", "is_live", "checkout", "deadline")
COPIED_M2M = ("tags", "channels", "playlists", "reminders")


def parse_urls(text):
    """Matndan havolalarni ajratadi: bo'sh joy, yangi qator, vergul yoki nuqta-vergul bilan
    ajratilgan, faqat http(s) bilan boshlanadiganlari, takrorlarsiz va tartib saqlangan holda."""
    seen = set()
    urls = []
    for token in URL_SPLIT.split(text or ""):
        token = token.strip()
        if not re.match(r"^https?://", token, re.IGNORECASE):
            continue
        key = token.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(token)
    return urls


def split_new_and_existing(model, urls):
    """Havolalarni bazada yo'qlari va allaqachon mavjudlariga ajratadi (url_hash bo'yicha)."""
    helper = model()
    new, existing, seen_hashes = [], [], set()
    for url in urls:
        normalized = helper.normalize_url(url)
        digest = helper.generate_hash(normalized)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        if model.objects.filter(url_hash=digest).exists():
            existing.append(url)
        else:
            new.append(url)
    return new, existing


def create_copies(model, template, form, urls, user=None):
    """`template` (saqlangan birinchi obyekt) sozlamalari bilan qolgan havolalar uchun obyektlar yaratadi."""
    created = []
    for url in urls:
        obj = model(url=url, user=user or getattr(template, "user", None))
        for name in COPIED_FIELDS:
            if hasattr(template, name):
                setattr(obj, name, getattr(template, name))
        obj.save()
        for name in COPIED_M2M:
            values = form.cleaned_data.get(name)
            if values is not None and hasattr(obj, name):
                getattr(obj, name).set(values)
        created.append(obj)
    return created
