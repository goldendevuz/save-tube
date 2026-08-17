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
