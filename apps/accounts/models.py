from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    """Per-user settings, including explicit consent for cloud AI processing."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preference")
    ai_provider = models.CharField(max_length=20, blank=True,
                                   help_text="Leave empty to use the server default (AI_PROVIDER).")
    allow_cloud_ai = models.BooleanField(
        default=False, help_text="Allow document text to be sent to a cloud AI provider.")
    default_template = models.ForeignKey("templates_manager.DocumentTemplate", null=True, blank=True,
                                         on_delete=models.SET_NULL)
    # Defaults pre-filled on cover pages (never copied from any reference file).
    organization = models.CharField(max_length=200, blank=True)
    department = models.CharField(max_length=200, blank=True)
    program = models.CharField(max_length=200, blank=True)
    author_name = models.CharField(max_length=150, blank=True)
    author_id = models.CharField(max_length=60, blank=True)

    def __str__(self):
        return f"Preferences for {self.user}"

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj
