"""
Loyiha darajasidagi zaxira (backup) va tiklash (restore) sahifasi.
Barcha model ma'lumotlarini bitta JSON faylga eksport/tiklash.
"""
import io
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core import management
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

EXCLUDE_APPS = ["contenttypes", "auth.permission", "admin.logentry", "sessions"]


def _model_counts():
    counts = {}
    for model in apps.get_models(include_auto_created=False):
        if model._meta.app_label in ("contenttypes", "sessions", "admin"):
            continue
        key = f"{model._meta.app_label}.{model._meta.model_name}"
        try:
            counts[key] = model.objects.count()
        except Exception:
            counts[key] = 0
    return counts


def _dump_all_data():
    buf = io.StringIO()
    management.call_command(
        "dumpdata",
        indent=2,
        exclude=EXCLUDE_APPS,
        stdout=buf,
    )
    return buf.getvalue()


@staff_member_required
@never_cache
def backup_page(request):
    context = {"model_counts": _model_counts()}

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "export":
            try:
                data = _dump_all_data()
                filename = f"savetube-backup-{datetime.now():%Y%m%d-%H%M}.json"
                response = HttpResponse(data, content_type="application/json")
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                return response
            except Exception as e:
                messages.error(request, f"Eksportda xatolik: {e}")

        elif action == "import":
            uploaded = request.FILES.get("file")
            if not uploaded:
                messages.error(request, "Fayl tanlanmadi.")
                return redirect(reverse("backup_page"))

            tmp_dir = Path(tempfile.mkdtemp(prefix="savetube-restore-"))
            try:
                if uploaded.name.endswith(".zip"):
                    with zipfile.ZipFile(uploaded) as zf:
                        zf.extractall(tmp_dir)
                    json_files = sorted(tmp_dir.rglob("*.json"))
                    if not json_files:
                        messages.error(request, "ZIP ichida JSON fayl topilmadi.")
                        return redirect(reverse("backup_page"))
                    fixture = json_files[0]
                else:
                    fixture = tmp_dir / "data.json"
                    fixture.write_bytes(uploaded.read())

                management.call_command("loaddata", str(fixture), verbosity=0)
                messages.success(request, "Ma'lumotlar muvaffaqiyatli tiklandi.")
            except Exception as e:
                messages.error(request, f"Tiklashda xatolik: {e}")
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

            return redirect(reverse("backup_page"))

    return render(request, "admin/backup.html", context)