from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Channel, Video, Playlist
from core.dashboard import invalidate_for_object


def _invalidate(*args, **kwargs):
    instance = kwargs.get("instance")
    if instance is not None and instance.pk is not None:
        invalidate_for_object(instance)


for MODEL in (Channel, Video, Playlist):
    post_save.connect(_invalidate, sender=MODEL, weak=False)
    post_delete.connect(_invalidate, sender=MODEL, weak=False)