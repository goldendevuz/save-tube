from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Q
from youtube.models import Video, Channel, Playlist
from core.redis_cache import (
    row_cache_get,
    row_cache_set,
    row_cache_delete,
    snapshot_get,
    snapshot_set,
    today_local,
    day_offset,
)

METRIC_LABELS = {
    "channels": "Kanallar",
    "subscribers": "Obunachilar",
    "videos": "Videolar",
    "shorts": "Shorts",
    "lives": "Jonli efirlar",
    "video_duration": "Videolar davomiyligi",
    "playlists": "Pleylistlar",
    "playlist_duration": "Pleylistlar davomiyligi",
}

def format_duration(s):
    if not s:
        return "-"
    d, rem = divmod(int(s), 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if d > 0: parts.append(f"{d} kun")
    if h > 0: parts.append(f"{h:02d} soat")
    if m > 0 or h > 0 or d > 0: parts.append(f"{m:02d} daqiqa")
    parts.append(f"{sec:02d} soniya")
    return " ".join(parts)


def _qs(scope):
    """Berilgan scope uchun Channel/Video/Playlist queryset'larini qaytaradi."""
    if scope == "all":
        ch, vid, pl = Channel.objects.all(), Video.objects.all(), Playlist.objects.all()
    elif scope.startswith("mine:"):
        uid = int(scope.split(":", 1)[1])
        ch = Channel.objects.filter(user_id=uid)
        vid = Video.objects.filter(user_id=uid)
        pl = Playlist.objects.filter(user_id=uid)
    else:
        return None
    return ch, vid, pl


def compute_totals(scope):
    qs = _qs(scope)
    if qs is None:
        return None
    ch, vid, pl = qs
    is_all = scope == "all"
    
    if not is_all:
        uid = int(scope.split(":", 1)[1])
        ch_count = Channel.objects.filter(
            Q(video__user_id=uid) | Q(playlist__user_id=uid)
        ).distinct().count()
    else:
        ch_count = ch.count()

    return {
        "channels": ch_count,
        "subscribers": ch.aggregate(total=Sum("subscriber_count"))["total"] or 0,
        "videos": (ch.aggregate(total=Sum("video_count"))["total"] or 0) if is_all else vid.count(),
        "shorts": ch.aggregate(total=Sum("shorts_count"))["total"] or 0 if is_all else 0,
        "lives": ch.aggregate(total=Sum("live_count"))["total"] or 0 if is_all else vid.filter(is_live=True).count(),
        "video_duration": vid.aggregate(total=Sum("duration"))["total"] or 0,
        "playlists": (ch.aggregate(total=Sum("playlist_count"))["total"] or 0) if is_all else pl.count(),
        "playlist_duration": pl.aggregate(total=Sum("duration"))["total"] or 0,
    }


def invalidate_for_object(instance):
    """Object saqlanganda/o'chirilganda tegishli scope'larning cache'sini yangilaydi.

    Faqat yig'indi haqiqatan o'zgarganda (xom cache bilan solishtirib) yozadi —
    "ma'lumot yangilansagina" tamoyili.
    """
    scopes = {"all"}
    uid = getattr(instance, "user_id", None)
    if uid:
        scopes.add(f"mine:{uid}")
    for scope in scopes:
        totals = compute_totals(scope)
        if totals is None:
            continue
        if row_cache_get(scope) != totals:
            row_cache_set(scope, totals)
            snapshot_set(scope, today_local(), totals)


def build_cards(scope):
    """Joriy holat va 7 kun avvalgi holatni solishtirib kartalar qaytaradi."""
    totals = row_cache_get(scope)
    if totals is None:
        totals = compute_totals(scope)
        if totals is None:
            return []
        row_cache_set(scope, totals)

    today = today_local()
    if snapshot_get(scope, today) is None:
        snapshot_set(scope, today, totals)

    past = snapshot_get(scope, day_offset(today, -7))

    cards = []
    for key in ("channels", "subscribers", "videos", "shorts", "lives", "video_duration", "playlists", "playlist_duration"):
        cur = totals.get(key, 0)
        prev = past.get(key, None) if past else None
        delta = None if prev is None else cur - prev
        pct = None
        if prev not in (None, 0) and delta is not None:
            pct = round((delta / prev) * 100, 1)
        
        metric_str = format_duration(cur) if key in ("video_duration", "playlist_duration") else f"{cur:,}"
        
        cards.append({
            "key": key,
            "title": METRIC_LABELS[key],
            "metric": metric_str,
            "delta": delta,
            "delta_pct": pct,
        })
    return cards


def _footer(card, prefix):
    if card["delta"] is None:
        return "7 kunlik taqqoslash yo'q"
    sign = "+" if card["delta"] >= 0 else ""
    
    if card["key"] in ("video_duration", "playlist_duration"):
        delta_val = format_duration(abs(card["delta"]))
        delta_str = f"{sign}{delta_val}"
    else:
        delta_str = f"{sign}{card['delta']:,}"
        
    part = f"{delta_str} ({sign}{card['delta_pct']}%)" if card["delta_pct"] is not None else delta_str
    return f"{prefix}| 7 kunda: {part}"


def dashboard_callback(request, context):
    """Unfold dashboard uchun ma'lumot: 1-qator JAMI, 2-qator MENING."""

    # 1-qator: Jami (barcha yozuvlar)
    row_all = build_cards("all")
    # 2-qator: Mening qo'shganlarim (joriy foydalanuvchi kiritgan yozuvlar soni)
    mine_scope = f"mine:{request.user.id}" if not request.user.is_anonymous else None
    row_mine = build_cards(mine_scope) if mine_scope else []
    # "Obunachilar" va "Shorts" ni Mening qatoridan tushiramiz
    row_mine = [card for card in row_mine if card["key"] not in ("subscribers", "shorts")]

    kpi = []
    for card in row_all:
        if card["key"] in ("video_duration", "playlist_duration"):
            continue
        kpi.append({
            "title": f"Jami · {card['title']}",
            "metric": card["metric"],
            "footer": _footer(card, "Barcha"),
            "subtitle": "Row 1",
        })
    for card in row_mine:
        kpi.append({
            "title": f"Mening · {card['title']}",
            "metric": card["metric"],
            "footer": f"{_footer(card, 'Mening')} · qo'shilgan yozuvlar soni",
            "subtitle": "Row 2",
        })

    # ── CRM: Bugungi videolar ──
    now = timezone.now()
    today = now.date()

    today_videos = (
        Video.objects.filter(checkout__date=today)
        .select_related("priority", "category")
        .prefetch_related("channels")
        .order_by("priority__id", "checkout")
    )

    # ── CRM: Muddati o'tgan videolar (checkout < bugun, status=new) ──
    overdue_videos = (
        Video.objects.filter(checkout__date__lt=today, status="new")
        .select_related("priority", "category")
        .prefetch_related("channels")
        .order_by("checkout")[:10]
    )

    # ── CRM: Bugungi pleylistlar ──
    today_playlists = (
        Playlist.objects.filter(checkout__date=today)
        .select_related("category", "channel")
        .order_by("checkout")
    )

    # ── CRM: Bugungi kanallar ──
    today_channels = (
        Channel.objects.filter(checkout__date=today)
        .select_related("category")
        .order_by("checkout")[:20]
    )

    # ── CRM: Umumiy statistika ──
    my_videos = Video.objects.all()
    total_count = my_videos.count()
    new_count = my_videos.filter(status="new").count()
    watched_count = my_videos.filter(status="watched").count()
    skipped_count = my_videos.filter(status="skipped").count()
    archived_count = my_videos.filter(status="archived").count()
    overdue_count = Video.objects.filter(checkout__date__lt=today, status="new").count()

    today_total = today_videos.count()
    today_new = today_videos.filter(status="new").count()
    today_watched = today_videos.filter(status="watched").count()
    today_skipped = today_videos.filter(status="skipped").count()

    total_duration = today_videos.filter(status="new").aggregate(total=Sum("duration"))["total"] or 0

    crm_stats = {
        "today_total": today_total,
        "today_new": today_new,
        "today_watched": today_watched,
        "today_skipped": today_skipped,
        "today_duration": format_duration(total_duration),
        "overdue_count": overdue_count,
        "total_count": total_count,
        "new_count": new_count,
        "watched_count": watched_count,
        "skipped_count": skipped_count,
        "archived_count": archived_count,
        "watch_pct": round((watched_count / total_count) * 100, 1) if total_count else 0,
    }

    week_ago = timezone.now() - timedelta(days=7)
    recent_videos = Video.objects.filter(created__gte=week_ago).count()
    recent_channels = Channel.objects.filter(created__gte=week_ago).count()

    context.update({
        "navigation": [
            {"title": "Bosh sahifa", "link": "/", "active": True},
        ],
        "kpi": kpi,
        "progress": [
            {
                "title": "Tizim barqarorligi",
                "description": "Barcha modullar to'g'ri ishlamoqda",
                "value": 100,
            }
        ],
        "today_videos": today_videos,
        "today_playlists": today_playlists,
        "today_channels": today_channels,
        "overdue_videos": overdue_videos,
        "crm_stats": crm_stats,
        "recent_videos_list": Video.objects.select_related("priority").prefetch_related("channels").order_by("-created")[:5],
    })

    return context