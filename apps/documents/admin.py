from django.contrib import admin

from .models import Document, DocumentVersion, JobOutput, ProcessingJob


class VersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    fields = ("version_number", "operation", "file_type", "is_current", "created_at")
    readonly_fields = fields


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "owner", "file_type", "status", "uploaded_at")
    list_filter = ("file_type", "status")
    search_fields = ("original_filename", "owner__username")
    inlines = [VersionInline]


@admin.register(ProcessingJob)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "operation", "document", "user", "status", "progress", "created_at")
    list_filter = ("operation", "status")


admin.site.register(JobOutput)
