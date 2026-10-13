from django.contrib import admin

from .models import ProcessingHistory


@admin.register(ProcessingHistory)
class ProcessingHistoryAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "document_name", "operation", "status")
    list_filter = ("status",)
