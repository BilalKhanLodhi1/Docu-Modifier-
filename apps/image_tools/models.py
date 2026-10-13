from django.db import models

from apps.documents.models import processed_upload_to


class DocumentImage(models.Model):
    """A record of an image edit applied to a document version."""
    version = models.ForeignKey("documents.DocumentVersion", on_delete=models.CASCADE, related_name="images")
    result_version = models.ForeignKey("documents.DocumentVersion", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="image_edits")
    image_index = models.PositiveIntegerField()
    original_image = models.FileField(upload_to=processed_upload_to, max_length=300)
    processed_image = models.FileField(upload_to=processed_upload_to, max_length=300, blank=True)
    image_format = models.CharField(max_length=10)
    width = models.PositiveIntegerField(null=True)
    height = models.PositiveIntegerField(null=True)
    caption = models.CharField(max_length=300, blank=True)
    location = models.CharField(max_length=200, blank=True)
    operations = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def owner_for_storage(self):
        return self.version.document.owner_id
