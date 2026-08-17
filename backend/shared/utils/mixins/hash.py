import hashlib


class HashMixin:

    HASH_FIELDS = []  # ["url"]

    def generate_hash(self, value):
        return hashlib.sha256(value.encode()).hexdigest()

    def save(self, *args, **kwargs):
        for field in self.HASH_FIELDS:
            value = getattr(self, field)
            if value:
                setattr(self, f"{field}_hash", self.generate_hash(value))
        super().save(*args, **kwargs)
