from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from core.backup import backup_page

from core.dashboard_views import bulk_shift_videos, video_preview_view, mark_video_watched, bulk_shift_playlists, bulk_shift_channels, channel_preview_view, playlist_preview_view
from core.views import homepage_redirect, RegisterView
from core.forms import SaveTubeLoginForm

admin.site.login_form = SaveTubeLoginForm

urlpatterns = [
    path('', homepage_redirect, name='home'),
    path('register/', RegisterView.as_view(), name='register'),
    path('admin/backup/', backup_page, name='backup_page'),
    path('admin/bulk-shift/', bulk_shift_videos, name='bulk_shift_videos'),
    path('admin/bulk-shift-playlists/', bulk_shift_playlists, name='bulk_shift_playlists'),
    path('admin/bulk-shift-channels/', bulk_shift_channels, name='bulk_shift_channels'),
    path('admin/video-preview/<int:pk>/', video_preview_view, name='video_preview_view'),
    path('admin/channel-preview/<int:pk>/', channel_preview_view, name='channel_preview_view'),
    path('admin/playlist-preview/<int:pk>/', playlist_preview_view, name='playlist_preview_view'),
    path('admin/video-preview/<int:pk>/mark-watched/', mark_video_watched, name='mark_video_watched'),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / 'static')
