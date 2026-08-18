from django.conf import settings


def ads(request):
    has_client = bool(getattr(settings, "ADSENSE_CLIENT", ""))
    return {
        "ads_enabled": has_client,
        "adsense_client": getattr(settings, "ADSENSE_CLIENT", ""),
        "adsense_slot": request.resolver_match.url_name if request.resolver_match else "",
        "adsense_slots": getattr(settings, "ADSENSE_SLOTS", {}),
    }