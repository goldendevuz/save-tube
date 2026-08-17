from django.apps import AppConfig


class YoutubeConfig(AppConfig):
    name = 'youtube'

    def ready(self):
        import youtube.signals  # noqa: F401