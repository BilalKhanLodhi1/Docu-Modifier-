"""Lightweight job runner.

Jobs are rows in ProcessingJob. Task functions are registered by operation
name and run either in a background thread (development default) or inline
(tests, or DOCUCRAFT_ASYNC_JOBS=False). Swapping in Celery only requires
calling `execute_job(job_id)` from a Celery task instead of a thread.
"""
import logging
import shutil
import threading
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import close_old_connections, transaction
from django.utils import timezone

from services.exceptions import DocuCraftError

from .models import DocumentVersion, JobOutput, ProcessingJob

log = logging.getLogger("docucraft.jobs")

REGISTRY = {}


def task(operation):
    def deco(fn):
        REGISTRY[operation] = fn
        return fn
    return deco


class DuplicateJob(Exception):
    def __init__(self, job):
        self.job = job


def start_job(document, user, operation, options=None, source_version=None):
    """Create and start a job. Raises DuplicateJob if the same job is already running."""
    _expire_stale_jobs()
    existing = ProcessingJob.objects.filter(document=document, operation=operation,
                                            status__in=("queued", "running")).first()
    if existing and existing.options == (options or {}):
        raise DuplicateJob(existing)
    job = ProcessingJob.objects.create(
        document=document, user=user, operation=operation, options=options or {},
        source_version=source_version or document.current_version, message="Waiting to start")
    from apps.history.models import record
    record(user, document, job.get_operation_display(), "queued", job=job)
    if getattr(settings, "DOCUCRAFT_ASYNC_JOBS", True):
        transaction.on_commit(lambda: threading.Thread(target=_thread_entry, args=(job.pk,), daemon=True).start())
    else:
        execute_job(job.pk)
        job.refresh_from_db()
    return job


def _thread_entry(job_id):
    close_old_connections()
    try:
        execute_job(job_id)
    finally:
        close_old_connections()


def execute_job(job_id):
    from apps.history.models import record
    job = ProcessingJob.objects.select_related("document", "source_version", "user").get(pk=job_id)
    fn = REGISTRY.get(job.operation)
    doc = job.document
    if fn is None:
        _fail(job, "This operation is not available.")
        return
    job.status, job.started_at, job.stage, job.progress = "running", timezone.now(), "extracting", 2
    job.heartbeat_at = job.started_at
    job.save(update_fields=["status", "started_at", "heartbeat_at", "stage", "progress"])
    doc.status = "processing"
    doc.save(update_fields=["status", "updated_at"])

    def progress(stage, percent, message=""):
        ProcessingJob.objects.filter(pk=job.pk).update(stage=stage, progress=min(99, int(percent)), message=message[:300],
                                                       heartbeat_at=timezone.now())

    try:
        result = fn(job, progress) or {}
    except DocuCraftError as exc:
        _fail(job, str(exc))
        record(job.user, doc, job.get_operation_display(), "failed", str(exc), job=job)
        return
    except Exception:
        log.exception("Job %s (%s) crashed", job.pk, job.operation)
        msg = "Something went wrong while processing this document. Your original file is unchanged. Please try again."
        _fail(job, msg)
        record(job.user, doc, job.get_operation_display(), "failed", msg, job=job)
        return
    job.refresh_from_db()
    job.status, job.stage, job.progress = "completed", "completed", 100
    job.completed_at = timezone.now()
    job.message = result.pop("message", "Done")[:300]
    job.result = {**job.result, **result}
    job.save()
    doc.status = "ready"
    doc.error_message = ""
    doc.save(update_fields=["status", "error_message", "updated_at"])
    ref = f"version {job.output_version.version_number}" if job.output_version else f"{job.outputs.count()} file(s)"
    record(job.user, doc, job.get_operation_display(), "completed", job.message, job=job, output_reference=ref)


def _fail(job, message):
    ProcessingJob.objects.filter(pk=job.pk).update(status="failed", stage="failed", error=message[:2000],
                                                   message=message[:300], completed_at=timezone.now())
    doc = job.document
    doc.status = "failed" if not doc.versions.exists() else "ready"
    doc.error_message = message[:2000]
    doc.save(update_fields=["status", "error_message", "updated_at"])


def _expire_stale_jobs():
    """Fail jobs that have reported no progress for twice the job timeout.

    Measured from the last progress report, not from creation, so a long job that is
    still working (a big document on a slow machine) is never cut off.
    """
    from django.db.models import Q
    limit = timezone.now() - timedelta(seconds=settings.DOCUCRAFT_JOB_TIMEOUT * 2)
    silent = (Q(heartbeat_at__lt=limit) | Q(heartbeat_at__isnull=True, created_at__lt=limit))
    for job in ProcessingJob.objects.filter(silent, status__in=("queued", "running")):
        _fail(job, "This job stopped reporting progress (the server may have restarted). Please try again.")


# ----------------------------------------------------------------------------
# File helpers used by tasks
# ----------------------------------------------------------------------------
def save_version(document, path, file_type, operation, summary="", parent=None, details=None, make_current=True):
    with transaction.atomic():
        last = document.versions.select_for_update().order_by("-version_number").first()
        number = (last.version_number + 1) if last else 1
        v = DocumentVersion(document=document, parent=parent, version_number=number, file_type=file_type,
                            operation=operation, summary=summary[:500], details=details or {})
        with open(path, "rb") as fh:
            v.file.save(f"v{number}.{file_type}", File(fh), save=False)
        v.save()
        if make_current:
            v.make_current()
    return v


def add_output(job, path, label, filename=None, file_type=None):
    path = Path(path)
    out = JobOutput(job=job, label=label[:200], filename=(filename or path.name)[:200],
                    file_type=(file_type or path.suffix.lstrip(".")).lower(), size=path.stat().st_size)
    with open(path, "rb") as fh:
        out.file.save(path.name, File(fh), save=False)
    out.save()
    return out


def source_path(job):
    v = job.source_version or job.document.current_version
    if v is None:
        raise DocuCraftError("This document has no stored version to process.")
    return Path(v.file.path), v


def copy_to(src, dst):
    shutil.copyfile(src, dst)
    return dst
