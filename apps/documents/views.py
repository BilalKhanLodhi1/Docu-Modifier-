import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import File
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.history.models import ProcessingHistory, record
from services import document_reader
from services.document_validator import safe_display_name
from services.exceptions import DocuCraftError

from .forms import PipelineForm, UploadForm
from .jobs import DuplicateJob, start_job
from .models import Document, DocumentVersion, JobOutput, ProcessingJob

log = logging.getLogger("docucraft.views")


def owned_document(request, pk):
    return get_object_or_404(Document, pk=pk, owner=request.user)


def owned_version(request, pk):
    return get_object_or_404(DocumentVersion.objects.select_related("document"), pk=pk, document__owner=request.user)


def launch(request, document, operation, options, source_version=None):
    """Start a job and redirect to its progress page (handles duplicates)."""
    try:
        job = start_job(document, request.user, operation, options, source_version=source_version)
    except DuplicateJob as dup:
        messages.info(request, "This job is already running. Showing its progress.")
        return redirect(dup.job.get_absolute_url())
    return redirect(job.get_absolute_url())


# ----------------------------------------------------------------------------
@login_required
def dashboard(request):
    docs = Document.objects.filter(owner=request.user)
    jobs = ProcessingJob.objects.filter(user=request.user)
    stats = {
        "total": docs.count(),
        "processed": jobs.filter(status="completed").values("document").distinct().count(),
        "running": jobs.filter(status__in=("queued", "running")).count(),
        "failed": jobs.filter(status="failed").count(),
    }
    recent_outputs = JobOutput.objects.filter(job__user=request.user).select_related("job__document").order_by("-created_at")[:6]
    recent_versions = DocumentVersion.objects.filter(document__owner=request.user).exclude(operation="upload") \
        .select_related("document").order_by("-created_at")[:6]
    return render(request, "dashboard.html", {
        "stats": stats,
        "recent_docs": docs[:6],
        "activity": ProcessingHistory.objects.filter(user=request.user)[:8],
        "recent_outputs": recent_outputs,
        "recent_versions": recent_versions,
        "upload_form": UploadForm(),
    })


@login_required
def workspace(request):
    q = request.GET.get("q", "").strip()
    kind = request.GET.get("type", "")
    docs = Document.objects.filter(owner=request.user).annotate(nversions=Count("versions"))
    if q:
        docs = docs.filter(original_filename__icontains=q)
    if kind in ("docx", "pdf"):
        docs = docs.filter(file_type=kind)
    return render(request, "documents/workspace.html", {"documents": docs, "upload_form": UploadForm(), "q": q, "kind": kind})


@login_required
@require_POST
def upload(request):
    form = UploadForm(request.POST, request.FILES)
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if not form.is_valid():
        err = "; ".join(e for errs in form.errors.values() for e in errs)
        if wants_json:
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return redirect(request.POST.get("next") or "documents:workspace")
    try:
        doc = create_document(request.user, form.cleaned_data["file"], form.detected_type)
    except DocuCraftError as exc:
        if wants_json:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect("documents:workspace")
    if wants_json:
        return JsonResponse({"ok": True, "url": doc.get_absolute_url(), "name": doc.original_filename})
    messages.success(request, f"Uploaded {doc.original_filename}.")
    return redirect(doc)


def create_document(user, uploaded, file_type):
    """Store an upload, inspect it, and create version 1 (pointing at the original file)."""
    display = safe_display_name(uploaded.name)
    doc = Document(owner=user, original_filename=display, file_type=file_type, file_size=uploaded.size)
    doc.original_file.save(display, uploaded, save=False)
    try:
        info = document_reader.inspect(doc.original_file.path, file_type)
    except DocuCraftError:
        doc.original_file.storage.delete(doc.original_file.name)
        raise
    doc.inspection = info
    doc.page_count = info.get("page_count")
    doc.status = "ready"
    doc.save()
    DocumentVersion.objects.create(document=doc, version_number=1, file=doc.original_file.name, file_type=file_type,
                                   operation="upload", summary="Original file (never modified)", is_current=True)
    record(user, doc, "Upload", "completed", f"{file_type.upper()}, {doc.file_size} bytes")
    return doc


@login_required
def detail(request, pk):
    doc = owned_document(request, pk)
    current = doc.current_version
    return render(request, "documents/detail.html", {
        "doc": doc, "current": current, "versions": doc.versions.all(),
        "jobs": doc.jobs.all()[:10], "info": doc.inspection,
        "pipeline_form": PipelineForm(user=request.user, initial={"steps": ["rewrite", "format"]}),
    })


@login_required
def preview(request, pk, version_pk):
    doc = owned_document(request, pk)
    version = get_object_or_404(DocumentVersion, pk=version_pk, document=doc)
    if version.file_type == "pdf":
        return render(request, "documents/_pdf_preview.html", {"version": version})
    try:
        html = document_reader.docx_preview_html(version.file.path)
    except Exception:
        log.exception("Preview failed for version %s", version.pk)
        html = "<p class='text-muted'>A preview could not be generated for this document. Download it to view.</p>"
    return render(request, "documents/_docx_preview.html", {"html": html, "version": version})


@login_required
@require_POST
def delete(request, pk):
    doc = owned_document(request, pk)
    name = doc.original_filename
    record(request.user, doc, "Delete", "completed", "Document and all versions deleted")
    for out in JobOutput.objects.filter(job__document=doc):
        out.delete()
    doc.versions.all().delete()
    doc.delete()
    messages.success(request, f"Deleted {name} and all of its versions.")
    return redirect("documents:workspace")


@login_required
@require_POST
def make_current(request, version_pk):
    version = owned_version(request, version_pk)
    version.make_current()
    messages.success(request, f"Version {version.version_number} is now the working version.")
    return redirect(version.document)


@login_required
def pipeline(request, pk):
    doc = owned_document(request, pk)
    form = PipelineForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        tpl = form.cleaned_data.get("template")
        from apps.accounts.models import UserPreference
        pref = UserPreference.for_user(request.user)
        options = {
            "steps": form.cleaned_data["steps"],
            "mode": form.cleaned_data.get("mode") or "professional",
            "template_id": tpl.pk if tpl else None,
            "template_name": tpl.name if tpl else "",
            "metadata": {"title": doc.inspection.get("title") or doc.stem.replace("_", " "),
                         "author": pref.author_name, "author_id": pref.author_id,
                         "organization": pref.organization, "department": pref.department,
                         "program": pref.program},
        }
        return launch(request, doc, "pipeline", options)
    for err in form.errors.values():
        messages.error(request, err[0])
    return redirect(doc)


# ----------------------------------------------------------------------------
# Secure downloads: every file is checked against the requesting user.
# ----------------------------------------------------------------------------
def _file_response(field, filename, inline=False):
    try:
        fh = field.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("File not found")
    resp = FileResponse(fh, as_attachment=not inline, filename=filename)
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    return resp


@login_required
def download_version(request, version_pk):
    v = owned_version(request, version_pk)
    return _file_response(v.file, v.download_name(), inline=request.GET.get("inline") == "1" and v.file_type == "pdf")


@login_required
def download_output(request, output_pk):
    out = get_object_or_404(JobOutput.objects.select_related("job"), pk=output_pk, job__user=request.user)
    return _file_response(out.file, out.filename, inline=request.GET.get("inline") == "1" and out.file_type == "pdf")


@login_required
def download_original(request, pk):
    doc = owned_document(request, pk)
    return _file_response(doc.original_file, doc.original_filename)


# ----------------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------------
@login_required
def job_detail(request, pk):
    job = get_object_or_404(ProcessingJob.objects.select_related("document", "output_version"), pk=pk, user=request.user)
    stages = {
        "rewrite": ["extracting", "rewriting", "validating", "formatting", "preparing"],
        "pipeline": ["extracting", "rewriting", "validating", "formatting", "converting", "preparing"],
        "format": ["extracting", "formatting", "preparing"],
        "image_edit": ["extracting", "enhancing", "formatting"],
        "split": ["extracting", "splitting", "preparing"],
        "convert_docx_pdf": ["extracting", "converting", "preparing"],
        "convert_pdf_docx": ["extracting", "converting", "preparing"],
    }.get(job.operation, ["extracting", "preparing"])
    labels = dict(ProcessingJob.STAGES)
    return render(request, "documents/job.html", {"job": job, "stages": [(s, labels[s]) for s in stages]})


@login_required
def job_status(request, pk):
    job = get_object_or_404(ProcessingJob, pk=pk, user=request.user)
    from .jobs import _expire_stale_jobs
    _expire_stale_jobs()
    job.refresh_from_db()
    return JsonResponse({"status": job.status, "stage": job.stage, "progress": job.progress,
                         "message": job.message, "error": job.error if job.status == "failed" else ""})


@login_required
@require_POST
def job_retry(request, pk):
    job = get_object_or_404(ProcessingJob, pk=pk, user=request.user)
    if job.status != "failed":
        return redirect(job.get_absolute_url())
    return launch(request, job.document, job.operation, job.options, source_version=job.source_version)
