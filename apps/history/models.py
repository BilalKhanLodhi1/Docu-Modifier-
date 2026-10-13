from django.conf import settings
from django.db import models


class ProcessingHistory(models.Model):
    """Append-only activity log; survives document deletion for auditing."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="history")
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="history")
    document_name = models.CharField(max_length=255)
    job = models.ForeignKey("documents.ProcessingJob", null=True, blank=True, on_delete=models.SET_NULL)
    operation = models.CharField(max_length=40)
    status = models.CharField(max_length=20)
    detail = models.CharField(max_length=500, blank=True)
    output_reference = models.CharField(max_length=300, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name_plural = "processing history"

    def __str__(self):
        return f"{self.operation} {self.status} ({self.document_name})"


def record(user, document, operation, status, detail="", job=None, output_reference=""):
    return ProcessingHistory.objects.create(
        user=user, document=document, document_name=document.original_filename if document else "",
        job=job, operation=operation, status=status, detail=detail[:500], output_reference=output_reference[:300])
