import traceback
from django.contrib import admin
from django.utils.html import format_html
from django.db import models as dj_models
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from dateutil.relativedelta import relativedelta
from unfold.admin import ModelAdmin
from import_export.admin import ImportExportModelAdmin
from unfold.contrib.import_export.forms import ExportForm, ImportForm, SelectableFieldsExportForm
from unfold.decorators import action

from shared.admin import BaseAdmin
from .models import (
    Playlist,
    Video,
    Category,
    Channel,
    Label,
    YouTubeConfig,
    AuditLog
)

# ----------------------------
# Channel date update actions
# ----------------------------
@action(description="Update selected channels' date for a month")
def update_channel_date_month(modeladmin, request, queryset):
    for obj in queryset:
        if hasattr(obj, 'checkout') and obj.checkout:
            obj.checkout = obj.checkout + relativedelta(months=1)
            obj.save()

@action(description="Update selected channels' date for a week")
def update_channel_date_week(modeladmin, request, queryset):
    for obj in queryset:
        if hasattr(obj, 'checkout') and obj.checkout:
            obj.checkout = obj.checkout + relativedelta(weeks=1)
            obj.save()

@action(description="Update selected channels' date for a day")
def update_channel_date_day(modeladmin, request, queryset):
    for obj in queryset:
        if hasattr(obj, 'checkout') and obj.checkout:
            obj.checkout = obj.checkout + relativedelta(days=1)
            obj.save()

@action(description="Statistikani yangilash (obunachilar, videolar, pleylistlar)")
def refresh_channel_stats(modeladmin, request, queryset):
    for obj in queryset:
        obj.fetch_channel_stats()
        obj.save(update_fields=["subscriber_count", "video_count", "playlist_count"])

@action(description="Davomiylikni yangilash")
def refresh_video_duration(modeladmin, request, queryset):
    for obj in queryset:
        obj.fetch_video_duration()
        obj.save(update_fields=["duration"])

@action(description="Videolar sonini yangilash")
def refresh_playlist_stats(modeladmin, request, queryset):
    for obj in queryset:
        obj.fetch_playlist_stats()
        obj.save(update_fields=["video_count"])


# ----------------------------
# Patch all models __str__ to always return string
# ----------------------------
def safe_str_method(original_str):
    def wrapped(self):
        try:
            val = original_str(self)
            return str(val) if val is not None else ""
        except Exception:
            return ""
    return wrapped

for model in [Playlist, Video, Category, Channel]:
    if hasattr(model, "__str__"):
        model.__str__ = safe_str_method(model.__str__)
    else:
        model.__str__ = lambda self: ""


def register_model(model):
    """
    Dynamically registers a model with the Django admin.
    """
    # ----------------------------
    # Prepare resource fields for import/export
    # ----------------------------
    resource_fields = {}
    for f in model._meta.fields:
        if isinstance(f, dj_models.ForeignKey):
            resource_fields[f.name] = fields.Field(
                column_name=f.name,
                attribute=f.name,
                widget=ForeignKeyWidget(f.related_model, 'id')
            )

    # Create dynamic resource class
    resource_class = type(
        f"{model.__name__}Resource",
        (resources.ModelResource,),
        {
            **resource_fields,
            "Meta": type("Meta", (), {"model": model})
        },
    )

    # ----------------------------
    # Determine admin base classes
    # ----------------------------
    # BaseAdmin (Unfold ModelAdmin) MUST be first so Unfold's UI overrides ImportExport UI
    base_classes = (BaseAdmin, ImportExportModelAdmin)

    # ----------------------------
    # Fields for admin display
    HIDDEN_LIST_FIELDS = {"id", "created", "modified", "user", "url_hash"}
    fields_list = [f.name for f in model._meta.fields]
    visible_fields = [f for f in fields_list if f not in HIDDEN_LIST_FIELDS]

    LIST_DISPLAY_ORDER = {
        "Channel":  ["title", "subscriber_count", "video_count", "shorts_count", "live_count", "playlist_count", "category", "total_watch", "has_new_video", "is_hidden", "is_archived", "url", "next_video", "checkout", "tags"],
        "Video":    ["title", "duration_display", "category", "priority", "is_hidden", "is_live", "url", "checkout", "channels", "status", "start_from", "deadline", "tags", "reminders"],
        "Playlist": ["title", "video_count", "category", "channel", "is_hidden", "url", "next_video", "checkout", "tags"],
        "Category": ["name", "priority"],
        "Label":    ["name"],
    }
    preferred_list = LIST_DISPLAY_ORDER.get(model.__name__)
    if preferred_list:
        list_display_fields = [f for f in preferred_list if f not in HIDDEN_LIST_FIELDS]
    else:
        list_display_fields = list(visible_fields) + [f.name for f in model._meta.many_to_many]

    admin_attrs = {
        "save_as": True,
        "resource_classes": [resource_class],
        "import_form_class": ImportForm,
        "export_form_class": SelectableFieldsExportForm,
        "list_filter_submit": True,
        "list_display": list_display_fields,
        "list_display_links": None,  # keyin to'g'ri o'rnatiladi
        "list_filter": [
            f.name
            for f in model._meta.fields
            if f.get_internal_type()
            in ["BooleanField", "NullBooleanField", "DateField", "DateTimeField", "ForeignKey"]
        ],
        "search_fields": [
            f.name
            for f in model._meta.fields
            if f.get_internal_type() in ["CharField", "TextField", "URLField"]
        ],
        "exclude": ["user", "url_hash"],
        "filter_horizontal": [f.name for f in model._meta.many_to_many],
        "save_on_top": True,
    }

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

    def get_search_results(self, request, queryset, search_term):
        base_queryset = queryset
        filtered_qs, use_distinct = BaseAdmin.get_search_results(self, request, queryset, search_term)
        
        if search_term:
            search_term_lower = search_term.lower()
            matching_ids = []
            
            # Encrypted fieldlar uchun Python darajasida qidiruv
            for obj in base_queryset:
                match = False
                for field in self.search_fields:
                    val = getattr(obj, field, None)
                    if val and isinstance(val, str) and search_term_lower in val.lower():
                        match = True
                        break
                if match:
                    matching_ids.append(obj.id)
                    
            if matching_ids:
                filtered_qs = filtered_qs | base_queryset.filter(id__in=matching_ids)
                
        return filtered_qs, use_distinct

    admin_attrs["has_add_permission"] = has_add_permission
    admin_attrs["has_change_permission"] = has_change_permission
    admin_attrs["has_delete_permission"] = has_delete_permission
    admin_attrs["get_search_results"] = get_search_results
    
    def save_model(self, request, obj, form, change):
        if hasattr(obj, 'user') and not obj.user:
            obj.user = request.user
        BaseAdmin.save_model(self, request, obj, form, change)
    
    admin_attrs["save_model"] = save_model

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        if model.__name__ in ("Channel", "Playlist"):
            obj = self.get_object(request, object_id)
            if obj:
                extra_context['related_videos'] = obj.video_set.all().order_by('-created')
        return ModelAdmin.change_view(self, request, object_id, form_url, extra_context=extra_context)

    admin_attrs["change_view"] = change_view

    def get_queryset(self, request):
        qs = self.model._default_manager.get_queryset()
        
        if hasattr(self.model, 'user') and not request.user.is_superuser:
            qs = qs.filter(user=request.user)
        
        # Yashirilganlarni va arxivlanganlarni sukut bo'yicha ko'rsatmaslik (faqat ro'yxat sahifasida)
        resolver = getattr(request, 'resolver_match', None)
        if resolver and resolver.url_name and resolver.url_name.endswith('_changelist'):
            if hasattr(self.model, 'is_hidden') and "is_hidden__exact" not in request.GET:
                qs = qs.filter(is_hidden=False)
            if hasattr(self.model, 'is_archived') and "is_archived__exact" not in request.GET:
                qs = qs.filter(is_archived=False)
        
        # video_count maydoni bor modellar uchun annotation va ordering
        has_video_count = any(f.name == "video_count" for f in self.model._meta.fields)
        has_subscriber_count = any(f.name == "subscriber_count" for f in self.model._meta.fields)
        
        if has_video_count:
            from django.db.models import Case, When, Value, IntegerField
            qs = qs.annotate(
                is_zero_video=Case(
                    When(video_count=0, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            if has_subscriber_count:
                qs = qs.order_by("is_zero_video", "video_count", "-subscriber_count", "-modified")
            else:
                qs = qs.order_by("is_zero_video", "video_count", "-modified")
        else:
            qs = qs.order_by("-modified")
        
        return qs

    admin_attrs["get_queryset"] = get_queryset

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "url":
            from django.forms.widgets import TextInput
            kwargs["widget"] = TextInput(attrs={
                "size": "80",
                "class": "vTextField",
                "placeholder": "https://www.youtube.com/...",
            })
        return BaseAdmin.formfield_for_dbfield(self, db_field, request, **kwargs)

    admin_attrs["formfield_for_dbfield"] = formfield_for_dbfield

    # ----------------------------
    # Per-model form field ordering
    # ----------------------------
    # title/description URL dan avtomatik fetch bo'ladi — formada umuman ko'rinmaydi
    FORM_FIELD_ORDER = {
        "Channel": ["url", "category", "tags", "total_watch", "next_video", "has_new_video", "is_hidden", "is_archived", "checkout"],
        "Video": ["url", "category", "priority", "channels", "tags", "status", "start_from", "is_hidden", "checkout", "deadline", "reminders"],
        "Playlist": ["url", "category", "channel", "tags", "next_video", "is_hidden", "checkout"],
        "Category": ["name", "priority"],
        "Label": ["name"],
    }

    preferred_order = FORM_FIELD_ORDER.get(model.__name__)
    if preferred_order:
        def get_fields(self, request, obj=None):
            # Faqat aniq belgilangan fieldlarni qaytarish (reverse relation'larni o'tkazib yuborish)
            return [f for f in preferred_order if f not in {"user", "url_hash"}]
        admin_attrs["get_fields"] = get_fields

    if model.__name__ == "Channel":
        admin_attrs["actions"] = [update_channel_date_month, update_channel_date_week, update_channel_date_day, refresh_channel_stats]
        admin_attrs["list_editable"] = ["category", "is_hidden", "is_archived"]
    elif model.__name__ == "Video":
        admin_attrs["actions"] = [refresh_video_duration]
        admin_attrs["list_editable"] = ["category", "priority", "is_hidden", "is_live"]
    elif model.__name__ == "Playlist":
        admin_attrs["actions"] = [refresh_playlist_stats]
        admin_attrs["list_editable"] = ["category", "is_hidden"]
    elif model.__name__ == "Category":
        admin_attrs["list_editable"] = ["priority"]

    # ----------------------------
    # Add ManyToMany display methods (get_tags, get_channels, ...)
    # ----------------------------
    m2m_method_map = {}  # {"tags": "get_tags", ...}
    for f in model._meta.many_to_many:
        method_name = f"get_{f.name}"
        m2m_method_map[f.name] = method_name

        def make_m2m(field_name):
            def m2m(self, obj):
                items = getattr(obj, field_name).all()
                text = ", ".join([str(i) for i in items[:5]]) + (" ..." if items.count() > 5 else "")
                if not text:
                    return "-"
                return format_html(
                    '<div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;" title="{}">{}</div>',
                    text, text
                )
            m2m.short_description = field_name
            return m2m

        admin_attrs[method_name] = make_m2m(f.name)

    # ----------------------------
    # Add safe text preview methods (short_url, short_description, ...)
    # ----------------------------
    text_method_map = {}  # {"url": "short_url", ...}
    for f in model._meta.fields:
        if isinstance(f, dj_models.TextField):
            method_name = f"short_{f.name}"
            text_method_map[f.name] = method_name

            def make_preview(field_name):
                def preview(self, obj):
                    val = getattr(obj, field_name)
                    if not val:
                        return ""
                    val_str = str(val).replace('\n', ' ').replace('\r', '')
                    short_text = (val_str[:50] + "...") if len(val_str) > 50 else val_str
                    return format_html(
                        '<div style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 250px;" title="{}">{}</div>',
                        val_str, short_text
                    )
                preview.short_description = field_name
                return preview

            admin_attrs[method_name] = make_preview(f.name)

    # ----------------------------
    # Force 1-line for DateTime/Date and Char fields (nowrap_checkout, ...)
    # ----------------------------
    nowrap_method_map = {}  # {"checkout": "nowrap_checkout", ...}
    for f in model._meta.fields:
        if isinstance(f, (dj_models.DateTimeField, dj_models.DateField, dj_models.CharField, dj_models.URLField)):
            method_name = f"nowrap_{f.name}"
            nowrap_method_map[f.name] = method_name

            def make_nowrap(field_name):
                def nowrap(self, obj):
                    val = getattr(obj, field_name)
                    if not val:
                        return "-"
                    if hasattr(val, "strftime"):
                        val_str = val.strftime("%Y-%m-%d %H:%M")
                    else:
                        val_str = str(val)
                    return format_html(
                        '<div style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px;" title="{}">{}</div>',
                        val_str, val_str
                    )
                nowrap.short_description = field_name
                return nowrap

            admin_attrs[method_name] = make_nowrap(f.name)

    # ----------------------------
    # Rebuild list_display with correct method names and explicit order
    # ----------------------------
    def format_short_number(num):
        if num == 0: return "0"
        if num >= 1_000_000_000:
            return f"{num / 1_000_000_000:f}".rstrip('0').rstrip('.') + " mlrd"
        if num >= 1_000_000:
            return f"{num / 1_000_000:f}".rstrip('0').rstrip('.') + " mln"
        if num >= 1_000:
            return f"{num / 1_000:f}".rstrip('0').rstrip('.') + " k"
        return str(num)

    def make_universal_nowrap(field_name):
        def col(self, obj):
            val = getattr(obj, field_name, None)
            if val is None or val == "":
                return "-"
            if isinstance(val, int) and not isinstance(val, bool):
                short_text = format_short_number(val)
                val_str = str(val)
            else:
                val_str = str(val).replace('\n', ' ').replace('\r', '')
                short_text = (val_str[:50] + "...") if len(val_str) > 50 else val_str
            return format_html(
                '<div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;" title="{}">{}</div>',
                val_str, short_text
            )
        if field_name == "duration_display":
            col.short_description = "Davomiyligi"
        else:
            col.short_description = field_name
        
        # Django uses the sorting of the original field if admin_order_field is set
        if field_name == "duration_display":
            col.admin_order_field = "duration"
        else:
            col.admin_order_field = field_name
        return col

    def resolve_field(fname):
        """Field nomini tegishli display method nomiga aylantirish, bo'lmasa universal nowrap yasash"""
        if fname in m2m_method_map:
            return m2m_method_map[fname]
        if fname in text_method_map:
            return text_method_map[fname]
        if fname in nowrap_method_map:
            return nowrap_method_map[fname]
        # Qolgan barcha fieldlar uchun universal nowrap
        method_name = f"col_{fname}"
        if method_name not in admin_attrs:
            admin_attrs[method_name] = make_universal_nowrap(fname)
        return method_name

    list_editable_fields = admin_attrs.get("list_editable", [])
    resolved_display = []
    for f in list_display_fields:
        if f in list_editable_fields:
            resolved_display.append(f)
        else:
            resolved_display.append(resolve_field(f))
    admin_attrs["list_display"] = resolved_display
    # Birinchi ustunni bosilishi mumkin qilish (qo'shish/tahrirlash tugmalari uchun)
    if resolved_display:
        admin_attrs["list_display_links"] = [resolved_display[0]]

    # ----------------------------
    # Add safe image thumbnail methods
    # ----------------------------
    for f in model._meta.fields:
        if isinstance(f, (dj_models.ImageField, dj_models.URLField, dj_models.CharField)):
            if 'thumbnail' in f.name.lower():
                method_name = f"show_{f.name}"

                def make_thumb(field_name):
                    def thumb(self, obj):
                        val = getattr(obj, field_name)
                        if val:
                            url = val.url if hasattr(val, "url") else val
                            return format_html(
                                '<a href="{0}" target="_blank">'
                                '<img src="{0}" width="60" height="60" style="object-fit: cover; border-radius: 8px;" />'
                                "</a>",
                                url,
                            )
                        return "-"
                    thumb.short_description = field_name
                    return thumb

                admin_attrs[method_name] = make_thumb(f.name)
                admin_attrs["list_display"].insert(0, method_name)

    # ----------------------------
    # Register admin class
    # ----------------------------
    admin_class = type(f"{model.__name__}Admin", base_classes, admin_attrs)
    admin.site.register(model, admin_class)


# ----------------------------
# Register all models
# ----------------------------
registered_models = [
    Playlist,
    Video,
    Category,
    Channel,
    Label
]

for model in registered_models:
    try:
        register_model(model)
    except Exception as e:
        print(f"\n❌ Failed to register {model.__name__}: {e}")
        traceback.print_exc()


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ("model", "object_id", "action", "user", "created_at")
    list_filter = ("model", "action", "created_at")
    search_fields = ("model", "object_id")
    readonly_fields = ("model", "object_id", "action", "user", "changes", "created_at")


@admin.register(YouTubeConfig)
class YouTubeConfigAdmin(ModelAdmin):
    """YouTube cookie sozlamalari — faqat bitta yozuv (singleton)."""

    def has_add_permission(self, request):
        return not YouTubeConfig.objects.exists() and YouTubeConfig.objects.count() == 0

    def has_delete_permission(self, request, obj=None):
        return False

    list_display = ("enabled", "updated_at")
