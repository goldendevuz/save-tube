from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from core.backup import backup_page

from core.dashboard_views import bulk_shift_videos, video_preview_view

urlpatterns = [
    path('admin/backup/', backup_page, name='backup_page'),
    path('admin/bulk-shift/', bulk_shift_videos, name='bulk_shift_videos'),
    path('admin/video-preview/<int:pk>/', video_preview_view, name='video_preview_view'),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / 'static')
