from django.contrib import admin

from .models import DocumentTemplate


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "owner", "is_shared", "updated_at")
