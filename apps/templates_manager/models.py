from django.conf import settings
from django.db import models
from django.db.models import Q


def logo_upload_to(instance, filename):
    from services.storage import internal_name
    from pathlib import Path
    owner = instance.owner_id or 0
    return f"logos/user_{owner}/{internal_name(Path(filename).suffix or '.png')}"


class DocumentTemplateQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self.filter(Q(owner__isnull=True) | Q(owner=user) | Q(is_shared=True))


class DocumentTemplate(models.Model):
    KIND_CHOICES = [("academic", "Academic / technical report"), ("corporate", "Corporate document")]

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="academic")
    config = models.JSONField(default=dict, help_text="Formatting configuration merged over the engine defaults.")
    logo = models.ImageField(upload_to=logo_upload_to, blank=True, null=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                              related_name="document_templates", help_text="Empty for built-in templates.")
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DocumentTemplateQuerySet.as_manager()

    class Meta:
        ordering = ["owner_id", "name"]

    def __str__(self):
        return self.name

    @property
    def is_builtin(self):
        return self.owner_id is None

    def merged(self):
        from services.docx_writer import merged_config
        return merged_config(self.config)
