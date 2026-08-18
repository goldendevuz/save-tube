"""
Django settings for core project.
"""

import os
import time
from pathlib import Path
from django.templatetags.static import static
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-ch!plx$q6obhk0xf_rq%hkni1)1%)v_1ghqw-qy(stays8+u#8'
FIELD_ENCRYPTION_KEY = b'1234567890123456789012345678901234567890123='

DEBUG = True
ALLOWED_HOSTS = ['*']

# Cloudflare Tunnel orqali keladigan domaynlar (CSRF origin tekshiruvi uchun)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', 'https://savetube.univel.uz').split(',')
    if origin.strip()
]

INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'unfold.contrib.inlines',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'unfold.contrib.import_export',
    'import_export',
    'shared',
    'youtube',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'shared.utils.middleware.CurrentUserMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processor.ads',
                'core.context_processor.unfold_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'uz'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_L10N = True
USE_TZ = False

# Loyiha faqat Asia/Tashkent mahalliy vaqti bilan ishlaydi
# (server/system soatiga qaramay, TZ majburan o'rnatiladi)
os.environ['TZ'] = TIME_ZONE
time.tzset()
LOCALE_PATHS = [BASE_DIR / 'locale']
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# --------------------------------------------------------------------------- #
# Unfold admin UI Configuration
# --------------------------------------------------------------------------- #
UNFOLD = {
    "SITE_TITLE": "SaveTube CRM",
    "SITE_HEADER": "SaveTube",
    "SITE_SUBHEADER": "Premium YouTube Management System",
    "SITE_SYMBOL": "play_circle",
    "DASHBOARD_CALLBACK": "core.dashboard.dashboard_callback",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "SHOW_BACK_BUTTON": True,
    "THEME": "dark",
    "BORDER_RADIUS": "8px",
    "COLORS": {
        "base": {
            "50": "250 250 249",
            "100": "245 245 244",
            "200": "231 229 228",
            "300": "214 211 209",
            "400": "168 162 158",
            "500": "120 113 108",
            "600": "87 83 78",
            "700": "68 64 60",
            "800": "41 37 36",
            "900": "28 25 23",
            "950": "12 10 9",
        },
        "primary": {
            "50": "236 253 246",
            "100": "209 250 233",
            "200": "167 243 214",
            "300": "110 231 189",
            "400": "52 211 160",
            "500": "16 183 132",
            "600": "5 148 104",
            "700": "4 117 85",
            "800": "6 95 70",
            "900": "6 78 59",
            "950": "2 44 34",
        },
        "font": {
            "subtle-light": "120 113 108",
            "subtle-dark": "156 163 175",
            "default-light": "87 83 78",
            "default-dark": "209 213 219",
            "important-light": "41 37 36",
            "important-dark": "243 244 246",
        },
    },
}

def _sidebar_navigation(request):
    """Yon menyu: 'Xavfsizlik va Jurnal' bo'limi faqat superuserlar uchun."""
    groups = [
        {
            "title": "Asosiy",
            "separator": False,
            "items": [
                {
                    "title": "Dashboard (Statistika)",
                    "icon": "dashboard",
                    "link": reverse_lazy("admin:index"),
                },
            ],
        },
        {
            "title": "YouTube Ma'lumotlari",
            "separator": True,
            "collapsible": False,
            "items": [
                {
                    "title": "Kanallar",
                    "icon": "smart_display",
                    "link": reverse_lazy("admin:youtube_channel_changelist"),
                },
                {
                    "title": "Videolar",
                    "icon": "video_library",
                    "link": reverse_lazy("admin:youtube_video_changelist"),
                },
                {
                    "title": "Pleylistlar",
                    "icon": "featured_play_list",
                    "link": reverse_lazy("admin:youtube_playlist_changelist"),
                },
                {
                    "title": "Kategoriyalar",
                    "icon": "category",
                    "link": reverse_lazy("admin:youtube_category_changelist"),
                },
                {
                    "title": "Teglar",
                    "icon": "label",
                    "link": reverse_lazy("admin:youtube_label_changelist"),
                },
            ],
        },
    ]
    if request.user.is_superuser:
        groups.append({
            "title": "Xavfsizlik va Jurnal",
            "separator": True,
            "collapsible": True,
            "items": [
                {
                    "title": "Foydalanuvchilar",
                    "icon": "group",
                    "link": reverse_lazy("admin:auth_user_changelist"),
                },
                {
                    "title": "Audit Log",
                    "icon": "history",
                    "link": reverse_lazy("admin:youtube_auditlog_changelist"),
                },
                {
                    "title": "Backup / Restore",
                    "icon": "backup",
                    "link": reverse_lazy("backup_page"),
                },
            ],
        })
    return groups


UNFOLD["SIDEBAR"] = {
    "show_search": True,
    "show_all_applications": True,
    "navigation": _sidebar_navigation,
}

LOGIN_URL = '/admin/login/'
LOGIN_REDIRECT_URL = '/admin/'
LOGOUT_REDIRECT_URL = '/admin/login/'

# --------------------------------------------------------------------------- #
# Ads (Google AdSense)
# Reklamalar faqat ADSENSE_CLIENT to'ldirilganda ishga tushadi.
# Sayt public bo'lganda (https + real trafik) AdSense onay beriladi.
# --------------------------------------------------------------------------- #
ADSENSE_CLIENT = os.environ.get('ADSENSE_CLIENT', '')
ADSENSE_SLOTS = {
    'content': os.environ.get('ADSENSE_SLOT_CONTENT', ''),
}
