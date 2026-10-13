"""Apply the retention policy and remove stale temporary files.

    python manage.py cleanup_documents            # uses DOCUCRAFT_RETENTION_DAYS
    python manage.py cleanup_documents --days 7 --dry-run

Schedule it daily (cron or launchd) in production.
"""
import shutil
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.documents.models import Document, JobOutput


class Command(BaseCommand):
    help = "Delete documents older than the retention period and clear temporary files."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--temp-hours", type=int, default=6)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        days = opts["days"] if opts["days"] is not None else settings.DOCUCRAFT_RETENTION_DAYS
        dry = opts["dry_run"]
        removed_docs = 0
        if days > 0:
            cutoff = timezone.now() - timedelta(days=days)
            old = Document.objects.filter(updated_at__lt=cutoff)
            removed_docs = old.count()
            if not dry:
                for doc in old:
                    for out in JobOutput.objects.filter(job__document=doc):
                        out.delete()
                    doc.versions.all().delete()
                    doc.delete()
        temp = Path(settings.MEDIA_ROOT) / "temporary"
        removed_tmp = 0
        if temp.exists():
            limit = time.time() - opts["temp_hours"] * 3600
            for p in temp.rglob("*"):
                try:
                    if p.is_file() and p.stat().st_mtime < limit:
                        removed_tmp += 1
                        if not dry:
                            p.unlink()
                except FileNotFoundError:
                    pass
            if not dry:
                for d in sorted((x for x in temp.rglob("*") if x.is_dir()), reverse=True):
                    try:
                        d.rmdir()
                    except OSError:
                        pass
        prefix = "Would remove" if dry else "Removed"
        self.stdout.write(f"{prefix} {removed_docs} document(s) older than {days} days and {removed_tmp} temporary file(s).")
