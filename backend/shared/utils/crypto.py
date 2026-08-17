from cryptography.fernet import Fernet
from django.conf import settings

fernet = Fernet(settings.FIELD_ENCRYPTION_KEY)


def encrypt(value: str) -> str:
    if value is None:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if value is None:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except Exception:
        return value
