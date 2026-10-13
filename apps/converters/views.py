from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.documents.models import ProcessingJob
from apps.documents.views import create_document, launch
from services.conversion_service import dependency_status
from services.exceptions import DocuCraftError

from .forms import ConvertForm


@login_required
def index(request):
    initial = {"document": request.GET.get("document")} if request.GET.get("document") else {}
    form = ConvertForm(request.POST or None, request.FILES or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            doc = create_document(request.user, d["file"], form.detected_type) if d.get("file") else d["document"]
        except DocuCraftError as exc:
            form.add_error("file", str(exc))
        else:
            v = doc.current_version
            if v.file_type == "docx":
                return launch(request, doc, "convert_docx_pdf", {}, source_version=v)
            return launch(request, doc, "convert_pdf_docx", {"ocr": d.get("ocr") or "auto",
                                                              "ocr_lang": d.get("ocr_lang") or "eng"}, source_version=v)
    deps = dependency_status()
    recent = ProcessingJob.objects.filter(user=request.user, operation__startswith="convert_").select_related("document")[:6]
    return render(request, "converters/index.html", {"form": form, "deps": deps, "recent": recent})
