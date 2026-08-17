from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages

def homepage_redirect(request):
    if request.user.is_authenticated:
        return redirect('admin:index')
    return redirect('admin:login')

class RegisterView(CreateView):
    template_name = 'admin/register.html'
    form_class = UserCreationForm
    success_url = reverse_lazy('admin:login')

    def form_valid(self, form):
        # Create user
        user = form.save()
        messages.success(self.request, "Ro'yxatdan muvaffaqiyatli o'tdingiz! Endi profilingizga kiring.")
        return super().form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('admin:index')
        return super().dispatch(request, *args, **kwargs)
