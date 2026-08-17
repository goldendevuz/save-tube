from django.forms.models import model_to_dict
from core.models.audit import AuditLog
from core.middleware import get_current_user


class AuditMixin:

    def get_model_name(self):
        return self.__class__.__name__

    def get_changes(self, old, new):
        changes = {}
        for field, old_value in old.items():
            new_value = new.get(field)
            if old_value != new_value:
                changes[field] = {
                    "old": old_value,
                    "new": new_value
                }
        return changes

    def save(self, *args, **kwargs):
        user = get_current_user()

        if self.pk:
            # UPDATE
            old_instance = self.__class__.objects.get(pk=self.pk)
            old_data = model_to_dict(old_instance)
            super().save(*args, **kwargs)
            new_data = model_to_dict(self)

            changes = self.get_changes(old_data, new_data)

            if changes:
                AuditLog.objects.create(
                    user=user,
                    model=self.get_model_name(),
                    object_id=self.pk,
                    action="update",
                    changes=changes
                )
        else:
            # CREATE
            super().save(*args, **kwargs)
            AuditLog.objects.create(
                user=user,
                model=self.get_model_name(),
                object_id=self.pk,
                action="create",
                changes=model_to_dict(self)
            )

    def delete(self, *args, **kwargs):
        user = get_current_user()
        data = model_to_dict(self)

        AuditLog.objects.create(
            user=user,
            model=self.get_model_name(),
            object_id=self.pk,
            action="delete",
            changes=data
        )

        super().delete(*args, **kwargs)
