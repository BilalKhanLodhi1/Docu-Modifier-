from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from services.ai_provider import get_provider
from services.conversion_service import dependency_status

from .forms import PreferenceForm, RegisterForm
from .models import UserPreference


def register(request):
    if request.user.is_authenticated:
        return redirect("documents:dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        UserPreference.for_user(user)
        login(request, user)
        messages.success(request, "Your account is ready. Upload a document to get started.")
        return redirect("documents:dashboard")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def settings_view(request):
    pref = UserPreference.for_user(request.user)
    form = PreferenceForm(request.POST or None, instance=pref, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("accounts:settings")
    provider = get_provider(pref.ai_provider or None)
    ok, msg = provider.available()
    return render(request, "accounts/settings.html", {
        "form": form, "provider": provider, "provider_ok": ok, "provider_msg": msg,
        "deps": dependency_status(), "max_upload": settings.DOCUCRAFT_MAX_UPLOAD_MB,
        "retention": settings.DOCUCRAFT_RETENTION_DAYS,
    })
