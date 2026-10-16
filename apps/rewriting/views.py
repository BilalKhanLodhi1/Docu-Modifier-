import difflib
import html

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe

from apps.accounts.models import UserPreference
from apps.documents.jobs import save_version
from apps.documents.models import ProcessingJob
from apps.documents.views import launch, owned_document
from apps.history.models import record
from services.ai_provider import get_provider
from services.rewrite_service import apply_rewrites
from services.storage import temp_workdir

from .forms import RewriteForm


@login_required
def index(request):
    initial = {}
    if request.GET.get("document"):
        initial["document"] = request.GET["document"]
    form = RewriteForm((request.POST if request.method == "POST" else None), user=request.user, initial=initial)
    pref = UserPreference.for_user(request.user)
    provider = get_provider(pref.ai_provider or None)
    ok, status_msg = provider.available()
    if request.method == "POST" and form.is_valid():
        doc = form.cleaned_data["document"]
        options = {k: form.cleaned_data[k] for k in ("mode", "audience", "custom_instructions")}
        return launch(request, doc, "rewrite", options)
    recent = ProcessingJob.objects.filter(user=request.user, operation__in=("rewrite", "pipeline"),
                                          status="completed").select_related("document")[:6]
    return render(request, "rewriting/index.html", {
        "form": form, "provider": provider, "provider_ok": ok, "provider_msg": status_msg,
        "cloud_blocked": provider.is_cloud and not pref.allow_cloud_ai, "recent": recent})


def word_diff(a, b):
    """Return (original_html, rewritten_html) with deletions/insertions highlighted."""
    aw, bw = a.split(), b.split()
    sm = difflib.SequenceMatcher(a=aw, b=bw, autojunk=False)
    left, right = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        x = html.escape(" ".join(aw[i1:i2]))
        y = html.escape(" ".join(bw[j1:j2]))
        if op == "equal":
            left.append(x)
            right.append(y)
        else:
            if x:
                left.append(f"<del>{x}</del>")
            if y:
                right.append(f"<ins>{y}</ins>")
    return mark_safe(" ".join(left)), mark_safe(" ".join(right))


@login_required
def review(request, job_pk):
    job = get_object_or_404(ProcessingJob.objects.select_related("document", "source_version"),
                            pk=job_pk, user=request.user, operation__in=("rewrite", "pipeline"))
    comparison = (job.result or {}).get("comparison")
    if job.status != "completed" or not comparison:
        messages.info(request, "This rewrite has no results to review yet.")
        return redirect(job.get_absolute_url())
    show = request.GET.get("show", "changed")
    rows = []
    for c in comparison:
        if show == "changed" and c["status"] not in ("changed", "reverted") and not c.get("flag"):
            continue
        if c["status"] == "changed":
            left, right = word_diff(c["original"], c["rewritten"])
        else:
            left = right = c["original"]
        rows.append({**c, "left": left, "right": right})
    if request.method == "POST" and job.operation == "rewrite":
        selected = set(request.POST.getlist("accept"))
        accepted = {c["id"]: c["rewritten"] for c in comparison if c["status"] == "changed" and c["id"] in selected}
        src = job.source_version
        with temp_workdir() as tmp:
            dst = tmp / "rewrite.docx"
            n = apply_rewrites(src.file.path, dst, accepted)
            v = save_version(job.document, dst, "docx", "rewrite",
                             f"AI rewrite: {n} of {job.result['stats']['changed']} changes accepted",
                             parent=src, details={"job": job.pk, "accepted": n})
        job.output_version = v
        job.save(update_fields=["output_version"])
        record(request.user, job.document, "Accept rewrite", "completed", f"{n} changes", job=job,
               output_reference=f"version {v.version_number}")
        messages.success(request, f"Saved version {v.version_number} with {n} accepted change(s).")
        return redirect(job.document)
    return render(request, "rewriting/review.html", {
        "job": job, "rows": rows, "stats": job.result.get("stats", {}), "show": show,
        "draft": job.outputs.first(), "total": len(comparison)})
