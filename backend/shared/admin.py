from unfold.admin import ModelAdmin

class BaseAdmin(ModelAdmin):
    list_per_page = 10

    # 🔒 faqat o'z datasini ko'rsatadi
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(self.model, "user"):
            return qs.filter(user=request.user)
        return qs

    # ✅ create paytida userni avtomatik set qiladi
    def save_model(self, request, obj, form, change):
        if not obj.pk:
            if hasattr(obj, "user"):
                obj.user = request.user
        super().save_model(request, obj, form, change)

    # 🔒 ForeignKey dropdown filtr
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            if hasattr(db_field.related_model, "user"):
                kwargs["queryset"] = db_field.related_model.objects.filter(user=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # 🔒 ManyToMany dropdown filtr
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            if hasattr(db_field.related_model, "user"):
                kwargs["queryset"] = db_field.related_model.objects.filter(user=request.user)
        return super().formfield_for_manytomany(db_field, request, **kwargs)
