from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth import login
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from core.forms import RegisterForm

MANAGE_MODELS = ["video", "channel", "playlist", "category", "priority", "label"]
MANAGE_ACTIONS = ["view", "add", "change", "delete"]


def _grant_user_permissions(user):
    codenames = {f"{action}_{model}" for model in MANAGE_MODELS for action in MANAGE_ACTIONS}
    perms = Permission.objects.filter(
        content_type__app_label="youtube",
        codename__in=codenames,
    )
    user.user_permissions.set(perms)

def homepage_redirect(request):
    if request.user.is_authenticated:
        return redirect('admin:index')
    return redirect('admin:login')

class RegisterView(CreateView):
    template_name = 'admin/register.html'
    form_class = RegisterForm
    success_url = reverse_lazy('admin:login')

    def form_valid(self, form):
        user = form.save(commit=False)
        user.is_staff = True
        user.save()
        _grant_user_permissions(user)
        messages.success(self.request, "Ro'yxatdan muvaffaqiyatli o'tdingiz! Endi profilingizga kiring.")
        return super().form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('admin:index')
        return super().dispatch(request, *args, **kwargs)
