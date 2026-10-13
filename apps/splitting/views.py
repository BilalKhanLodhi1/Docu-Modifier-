import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.documents.models import ProcessingJob
from apps.documents.views import launch, owned_document
from services import split_service
from services.exceptions import DocuCraftError

from .forms import DOCX_METHODS, PDF_METHODS, SplitForm


@login_required
def index(request):
    initial = {"document": request.GET.get("document")} if request.GET.get("document") else {}
    form = SplitForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        doc = d["document"]
        v = doc.current_version
        try:
            if v.file_type == "pdf":
                parts = split_service.plan_pdf_split(v.file.path, d["method"], d["ranges"], d["pages_per_file"])
            else:
                method = "heading" if d["method"] == "custom" else d["method"]
                parts = split_service.plan_docx_split(v.file.path, method, d.get("heading_level") or 1)
        except DocuCraftError as exc:
            form.add_error(None, str(exc))
        else:
            token = uuid.uuid4().hex
            request.session[f"split_{token}"] = {"doc": doc.pk, "version": v.pk, "parts": parts,
                                                 "method": d["method"]}
            return redirect(f"{request.path}preview/{token}/")
    recent = ProcessingJob.objects.filter(user=request.user, operation="split").select_related("document")[:5]
    return render(request, "splitting/index.html", {"form": form, "recent": recent,
                                                    "pdf_methods": PDF_METHODS, "docx_methods": DOCX_METHODS})


@login_required
def preview(request, token):
    plan = request.session.get(f"split_{token}")
    if not plan:
        messages.info(request, "That split preview has expired. Set it up again.")
        return redirect("splitting:index")
    doc = owned_document(request, plan["doc"])
    version = doc.versions.get(pk=plan["version"])
    parts = plan["parts"]
    if request.method == "POST":
        chosen = []
        for i, part in enumerate(parts):
            if request.POST.get(f"include_{i}") == "1":
                name = (request.POST.get(f"name_{i}") or "").strip()[:80]
                chosen.append({**part, "filename": name})
        if not chosen:
            messages.error(request, "Select at least one part to create.")
        else:
            del request.session[f"split_{token}"]
            options = {"parts": chosen, "method": plan["method"],
                       "combine": request.POST.get("combine") == "1" and version.file_type == "docx"}
            return launch(request, doc, "split", options, source_version=version)
    warning = None
    if version.file_type == "docx":
        warning = ("Each part keeps the original styles, headers and footers. Cross-references, a table of contents "
                   "and page numbers that point to other parts will not update automatically.")
    return render(request, "splitting/preview.html", {"doc": doc, "version": version, "parts": parts,
                                                      "warning": warning, "custom": plan["method"] == "custom"})
