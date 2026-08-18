from django.shortcuts import redirect
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from youtube.models import Video

def bulk_shift_videos(request):
    if not request.user.is_staff:
        return redirect('admin:index')
        
    if request.method == "POST":
        video_ids = request.POST.getlist("video_ids")
        shift_type = request.POST.get("shift_type")
        
        if not video_ids:
            messages.warning(request, "Hech qanday video tanlanmadi!")
            return redirect(request.META.get('HTTP_REFERER', '/admin/'))
            
        videos = Video.objects.filter(id__in=video_ids)
        updated_count = 0
        
        for video in videos:
            if not video.checkout:
                video.checkout = timezone.now()
            
            if shift_type == "day":
                video.checkout = video.checkout + timedelta(days=1)
            elif shift_type == "week":
                video.checkout = video.checkout + timedelta(weeks=1)
            elif shift_type == "month":
                video.checkout = video.checkout + relativedelta(months=1)
            elif shift_type == "year":
                video.checkout = video.checkout + relativedelta(years=1)
            else:
                continue
                
            video.save()
            updated_count += 1
            
        if updated_count > 0:
            messages.success(request, f"{updated_count} ta video vaqti muvaffaqiyatli surildi!")
    return redirect(request.META.get('HTTP_REFERER', '/admin/'))

def bulk_shift_playlists(request):
    from youtube.models import Playlist
    if not request.user.is_staff:
        return redirect('admin:index')
        
    if request.method == "POST":
        playlist_ids = request.POST.getlist("playlist_ids")
        shift_type = request.POST.get("shift_type")
        
        if not playlist_ids:
            messages.warning(request, "Hech qanday pleylist tanlanmadi!")
            return redirect(request.META.get('HTTP_REFERER', '/admin/'))
            
        playlists = Playlist.objects.filter(id__in=playlist_ids)
        updated_count = 0
        
        for pl in playlists:
            if not pl.checkout:
                pl.checkout = timezone.now()
            
            if shift_type == "day":
                pl.checkout = pl.checkout + timedelta(days=1)
            elif shift_type == "week":
                pl.checkout = pl.checkout + timedelta(weeks=1)
            elif shift_type == "month":
                pl.checkout = pl.checkout + relativedelta(months=1)
            elif shift_type == "year":
                pl.checkout = pl.checkout + relativedelta(years=1)
            else:
                continue
                
            pl.save()
            updated_count += 1
            
        if updated_count > 0:
            messages.success(request, f"{updated_count} ta pleylistning tekshirish vaqti surildi!")
            
    return redirect(request.META.get('HTTP_REFERER', '/admin/'))

def bulk_shift_channels(request):
    from youtube.models import Channel
    if not request.user.is_staff:
        return redirect('admin:index')
        
    if request.method == "POST":
        channel_ids = request.POST.getlist("channel_ids")
        shift_type = request.POST.get("shift_type")
        
        if not channel_ids:
            messages.warning(request, "Hech qanday kanal tanlanmadi!")
            return redirect(request.META.get('HTTP_REFERER', '/admin/'))
            
        channels = Channel.objects.filter(id__in=channel_ids)
        updated_count = 0
        
        for ch in channels:
            if not ch.checkout:
                ch.checkout = timezone.now()
            
            if shift_type == "day":
                ch.checkout = ch.checkout + timedelta(days=1)
            elif shift_type == "week":
                ch.checkout = ch.checkout + timedelta(weeks=1)
            elif shift_type == "month":
                ch.checkout = ch.checkout + relativedelta(months=1)
            elif shift_type == "year":
                ch.checkout = ch.checkout + relativedelta(years=1)
            else:
                continue
                
            ch.save()
            updated_count += 1
            
        if updated_count > 0:
            messages.success(request, f"{updated_count} ta kanalning tekshirish vaqti surildi!")
            
    return redirect(request.META.get('HTTP_REFERER', '/admin/'))

def video_preview_view(request, pk):
    from django.shortcuts import get_object_or_404, render
    from youtube.models import Video
    
    if not request.user.is_staff:
        return redirect('admin:index')
        
    video = get_object_or_404(Video, pk=pk)
    stats = video.fetch_realtime_stats()
    
    # Extract video ID for iframe
    import re
    video_id = None
    if video.url:
        m = re.search(r'(?:v=|\/shorts\/|\/embed\/|\.be\/|\/v\/|\/watch\?v=|\/watch\?.+&v=)([0-9A-Za-z_-]{11})', video.url)
        if m:
            video_id = m.group(1)
            
    from django.contrib import admin
    context = dict(
        admin.site.each_context(request),
        video=video,
        stats=stats,
        video_id=video_id,
        title=f"Ko'rish: {video.title}",
    )
    return render(request, "admin/youtube_video_view.html", context)

def channel_preview_view(request, pk):
    from django.shortcuts import get_object_or_404, render
    from youtube.models import Channel
    
    if not request.user.is_staff:
        return redirect('admin:index')
        
    channel = get_object_or_404(Channel, pk=pk)
    related_videos = channel.video_set.all().order_by('-created')
    
    from django.contrib import admin
    context = dict(
        admin.site.each_context(request),
        channel=channel,
        related_videos=related_videos,
        title=f"Kanal: {channel.title}",
    )
    return render(request, "admin/youtube_channel_view.html", context)

def playlist_preview_view(request, pk):
    from django.shortcuts import get_object_or_404, render
    from youtube.models import Playlist
    
    if not request.user.is_staff:
        return redirect('admin:index')
        
    playlist = get_object_or_404(Playlist, pk=pk)
    related_videos = playlist.video_set.all().order_by('-created')
    
    from django.contrib import admin
    context = dict(
        admin.site.each_context(request),
        playlist=playlist,
        related_videos=related_videos,
        title=f"Pleylist: {playlist.title}",
    )
    return render(request, "admin/youtube_playlist_view.html", context)

def mark_video_watched(request, pk):
    from django.shortcuts import get_object_or_404
    from youtube.models import Video
    
    if not request.user.is_staff:
        return redirect('admin:index')
        
    video = get_object_or_404(Video, pk=pk)
    if request.method == "POST":
        if video.status == 'watched':
            video.status = 'new'
            video.is_hidden = False
            video.save()
            messages.info(request, f"'{video.title}' yangi deb belgilandi va ro'yxatga qaytarildi.")
        else:
            video.status = 'watched'
            video.is_hidden = True
            video.save()
            messages.success(request, f"'{video.title}' ko'rildi deb belgilandi va yashirildi!")
        
    return redirect(request.META.get('HTTP_REFERER', 'video_preview_view'))
