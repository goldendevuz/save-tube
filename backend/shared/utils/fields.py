from django.db import models
from shared.utils.crypto import encrypt, decrypt


class EncryptedTextField(models.TextField):
    """TextField that automatically encrypts and decrypts values in the database."""

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt(value)

    def to_python(self, value):
        if value is None:
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return encrypt(value)


class EncryptedCharField(models.CharField):
    """CharField that automatically encrypts and decrypts values in the database."""

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt(value)

    def to_python(self, value):
        if value is None:
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return encrypt(value)
