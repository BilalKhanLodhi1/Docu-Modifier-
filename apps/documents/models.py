from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse


def _storage_path(instance, filename, kind):
    from services.storage import internal_name, user_subdir
    user_id = getattr(instance, "owner_id", None) or instance.owner_for_storage()
    return f"{user_subdir(user_id, kind)}/{internal_name(Path(filename).suffix or '.bin')}"


def original_upload_to(instance, filename):
    """originals/user_<id>/YYYY/MM/<uuid>.<ext> — never the user's filename."""
    return _storage_path(instance, filename, "originals")


def processed_upload_to(instance, filename):
    return _storage_path(instance, filename, "processed")


class DocumentQuerySet(models.QuerySet):
    def with_current_type(self):
        """Annotate `current_type` (docx/pdf of the working version) in one query."""
        from django.db.models import OuterRef, Subquery
        from django.db.models.functions import Coalesce
        versions = DocumentVersion.objects.filter(document=OuterRef("pk"))
        current = versions.filter(is_current=True).order_by("-version_number").values("file_type")[:1]
        latest = versions.order_by("-version_number").values("file_type")[:1]
        return self.annotate(current_type=Coalesce(Subquery(current), Subquery(latest)))

    def word_documents(self):
        return self.with_current_type().filter(current_type="docx")


class Document(models.Model):
    TYPE_CHOICES = [("docx", "Word"), ("pdf", "PDF")]
    STATUS_CHOICES = [("uploaded", "Uploaded"), ("processing", "Processing"), ("ready", "Ready"), ("failed", "Failed")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    original_filename = models.CharField(max_length=255)
    original_file = models.FileField(upload_to=original_upload_to, max_length=300)
    file_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    file_size = models.PositiveBigIntegerField(default=0)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    inspection = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="uploaded")
    active_template = models.ForeignKey("templates_manager.DocumentTemplate", null=True, blank=True,
                                        on_delete=models.SET_NULL)
    error_message = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["owner", "-uploaded_at"])]

    def __str__(self):
        return self.original_filename

    def get_absolute_url(self):
        return reverse("documents:detail", args=[self.pk])

    @property
    def stem(self):
        return Path(self.original_filename).stem

    @property
    def current_version(self):
        return self.versions.filter(is_current=True).order_by("-version_number").first() or \
            self.versions.order_by("-version_number").first()

    def applied_operations(self):
        return list(self.versions.exclude(operation="upload").values_list("operation", flat=True))


class DocumentVersion(models.Model):
    OPERATIONS = [
        ("upload", "Original upload"),
        ("rewrite", "AI rewrite"),
        ("format", "Template formatting"),
        ("image_edit", "Image edit"),
        ("convert_pdf_docx", "Converted from PDF"),
        ("pipeline", "Combined workflow"),
    ]
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    version_number = models.PositiveIntegerField()
    file = models.FileField(upload_to=processed_upload_to, max_length=300)
    file_type = models.CharField(max_length=10, choices=Document.TYPE_CHOICES)
    operation = models.CharField(max_length=30, choices=OPERATIONS)
    summary = models.CharField(max_length=500, blank=True)
    details = models.JSONField(default=dict, blank=True)
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_number"]
        unique_together = [("document", "version_number")]

    def __str__(self):
        return f"{self.document} v{self.version_number}"

    def owner_for_storage(self):
        return self.document.owner_id

    @property
    def is_original(self):
        return self.operation == "upload"

    def download_name(self):
        if self.is_original:
            return self.document.original_filename
        return f"{self.document.stem}_v{self.version_number}_{self.operation}.{self.file_type}"

    def make_current(self):
        self.document.versions.exclude(pk=self.pk).update(is_current=False)
        self.is_current = True
        self.save(update_fields=["is_current"])


class ProcessingJob(models.Model):
    OPERATIONS = [
        ("rewrite", "AI rewrite"),
        ("format", "Apply template"),
        ("image_edit", "Image edit"),
        ("split", "Split document"),
        ("convert_docx_pdf", "Word to PDF"),
        ("convert_pdf_docx", "PDF to Word"),
        ("pipeline", "Combined workflow"),
    ]
    STATUS = [("queued", "Queued"), ("running", "Running"), ("completed", "Completed"), ("failed", "Failed")]
    STAGES = [
        ("queued", "Queued"), ("extracting", "Extracting content"), ("rewriting", "Rewriting"),
        ("validating", "Validating"), ("enhancing", "Enhancing images"), ("formatting", "Formatting"),
        ("splitting", "Splitting"), ("converting", "Converting"), ("preparing", "Preparing download"),
        ("completed", "Completed"), ("failed", "Failed"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="jobs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="jobs")
    operation = models.CharField(max_length=30, choices=OPERATIONS)
    status = models.CharField(max_length=20, choices=STATUS, default="queued")
    stage = models.CharField(max_length=20, choices=STAGES, default="queued")
    progress = models.PositiveSmallIntegerField(default=0)
    message = models.CharField(max_length=300, blank=True)
    options = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    source_version = models.ForeignKey(DocumentVersion, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="jobs_as_source")
    output_version = models.ForeignKey(DocumentVersion, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="jobs_as_output")
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    # Updated on every progress report; the stale-job watchdog measures silence from here.
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_operation_display()} #{self.pk}"

    def get_absolute_url(self):
        return reverse("documents:job", args=[self.pk])

    @property
    def is_active(self):
        return self.status in ("queued", "running")


class JobOutput(models.Model):
    """Extra files produced by a job (split parts, PDF exports, ZIP archives, drafts)."""
    job = models.ForeignKey(ProcessingJob, on_delete=models.CASCADE, related_name="outputs")
    file = models.FileField(upload_to=processed_upload_to, max_length=300)
    label = models.CharField(max_length=200)
    filename = models.CharField(max_length=200)
    file_type = models.CharField(max_length=10)
    size = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def owner_for_storage(self):
        return self.job.user_id
