from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from services.ai_provider import provider_choices

from .models import UserPreference


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class PreferenceForm(forms.ModelForm):
    ai_provider = forms.ChoiceField(required=False)

    class Meta:
        model = UserPreference
        fields = ("ai_provider", "allow_cloud_ai", "default_template", "organization", "department",
                  "program", "author_name", "author_id")
        labels = {"allow_cloud_ai": "Allow sending document text to a cloud AI provider",
                  "author_name": "Your name", "author_id": "Student or employee ID"}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.templates_manager.models import DocumentTemplate
        self.fields["ai_provider"].choices = [("", "Server default")] + provider_choices()
        self.fields["default_template"].queryset = DocumentTemplate.objects.visible_to(user)
