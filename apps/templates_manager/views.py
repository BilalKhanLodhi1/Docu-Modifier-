from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import File
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import UserPreference
from apps.documents.views import launch, owned_document
from services.docx_writer import heading_outline

from .forms import FormatForm, TemplateForm
from .models import DocumentTemplate


@login_required
def index(request):
    templates = DocumentTemplate.objects.visible_to(request.user)
    return render(request, "templates_manager/index.html", {"templates": templates})


def _editable(request, pk):
    tpl = get_object_or_404(DocumentTemplate, pk=pk)
    if tpl.owner_id != request.user.id:
        raise Http404
    return tpl


@login_required
def create(request):
    source = None
    if request.GET.get("from"):
        source = get_object_or_404(DocumentTemplate.objects.visible_to(request.user), pk=request.GET["from"])
    instance = DocumentTemplate(config=dict(source.config) if source else {},
                                kind=source.kind if source else "academic",
                                name=f"{source.name} (copy)" if source else "",
                                description=source.description if source else "")
    form = TemplateForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        tpl = form.save(commit=False)
        tpl.owner = request.user
        if source and source.logo and not form.cleaned_data.get("logo"):
            tpl.logo.save(source.logo.name.rsplit("/", 1)[-1], File(source.logo.open("rb")), save=False)
        tpl.save()
        messages.success(request, f"Created template {tpl.name}.")
        return redirect("templates_manager:index")
    return render(request, "templates_manager/form.html", {"form": form, "creating": True})


@login_required
def edit(request, pk):
    tpl = _editable(request, pk)
    form = TemplateForm(request.POST or None, request.FILES or None, instance=tpl)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Template saved.")
        return redirect("templates_manager:index")
    return render(request, "templates_manager/form.html", {"form": form, "tpl": tpl})


@login_required
@require_POST
def delete(request, pk):
    tpl = _editable(request, pk)
    tpl.delete()
    messages.success(request, "Template deleted.")
    return redirect("templates_manager:index")


@login_required
def apply(request, doc_pk):
    doc = owned_document(request, doc_pk)
    current = doc.current_version
    if current.file_type != "docx":
        messages.warning(request, "Templates apply to Word documents. Convert this PDF to Word first.")
        return redirect("converters:index")
    sections = heading_outline(current.file.path)
    pref = UserPreference.for_user(request.user)
    initial = {
        "template": request.GET.get("template") or (doc.active_template_id or pref.default_template_id),
        "title": doc.inspection.get("title") or doc.stem.replace("_", " "),
        "organization": pref.organization, "department": pref.department, "program": pref.program,
        "author": pref.author_name, "author_id": pref.author_id, "date": date.today().strftime("%d %B %Y"),
    }
    form = FormatForm(request.POST or None, request.FILES or None, user=request.user, sections=sections, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        tpl = d["template"]
        options = {
            "template_id": tpl.pk, "template_name": tpl.name,
            "metadata": {k: d[k] for k in FormatForm.META_FIELDS},
            "include_cover": d["include_cover"], "include_toc": d["include_toc"],
            "overrides": {"page_numbers": d["page_numbers"]},
            "scope_ids": d["sections"] if d["scope"] == "selected" else None,
        }
        if d.get("logo"):
            from django.core.files.storage import default_storage
            from services.storage import internal_name, user_subdir
            name = default_storage.save(f"{user_subdir(request.user.id, 'logos')}/{internal_name('.png')}", d["logo"])
            options["logo_path"] = default_storage.path(name)
        return launch(request, doc, "format", options)
    return render(request, "templates_manager/apply.html", {"doc": doc, "form": form, "current": current,
                                                            "has_sections": bool(sections)})
