import base64
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from PIL import Image

from apps.documents.models import Document
from apps.documents.views import launch, owned_document
from services import image_service
from services.exceptions import DocuCraftError
from services.storage import internal_name, user_subdir

MAX_REPLACEMENT_MB = 15
TECHNICAL_HINTS = ("figure", "fig.", "diagram", "chart", "graph", "screenshot", "output", "logo", "table", "plot")


def _docx_version(request, doc_pk):
    doc = owned_document(request, doc_pk)
    v = doc.current_version
    if v.file_type != "docx":
        raise DocuCraftError("The image editor works with Word documents. Convert this PDF to Word first.")
    return doc, v


@login_required
def index(request):
    docs = [d for d in Document.objects.filter(owner=request.user) if d.current_version and d.current_version.file_type == "docx"]
    return render(request, "image_tools/index.html", {"documents": docs})


@login_required
def gallery(request, doc_pk):
    try:
        doc, v = _docx_version(request, doc_pk)
    except DocuCraftError as exc:
        messages.warning(request, str(exc))
        return redirect("image_tools:index")
    images = image_service.list_images(v.file.path)
    return render(request, "image_tools/gallery.html", {"doc": doc, "version": v, "images": images})


@login_required
def raw(request, doc_pk, index):
    doc, v = _docx_version(request, doc_pk)
    data = image_service.get_image_bytes(v.file.path, index)
    try:
        import io
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "PNG").upper()
            if fmt not in ("PNG", "JPEG", "GIF", "WEBP", "BMP"):
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, "PNG")
                data, fmt = buf.getvalue(), "PNG"
    except Exception:
        return HttpResponse(status=415)
    resp = HttpResponse(data, content_type=f"image/{fmt.lower()}")
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def _read_ops(request):
    try:
        ops = json.loads(request.POST.get("ops") or "{}")
    except json.JSONDecodeError:
        ops = {}
    return ops if isinstance(ops, dict) else {}


def _replacement(request):
    f = request.FILES.get("replacement")
    if not f:
        return None
    if f.size > MAX_REPLACEMENT_MB * 1024 * 1024:
        raise DocuCraftError(f"The replacement image must be smaller than {MAX_REPLACEMENT_MB} MB.")
    try:
        with Image.open(f) as im:
            im.verify()
    except Exception:
        raise DocuCraftError("The replacement file is not a supported image.")
    f.seek(0)
    return f.read()


@login_required
def editor(request, doc_pk, index):
    try:
        doc, v = _docx_version(request, doc_pk)
        images = image_service.list_images(v.file.path)
    except DocuCraftError as exc:
        messages.warning(request, str(exc))
        return redirect("image_tools:index")
    if index >= len(images):
        messages.warning(request, "That image is no longer in the current version.")
        return redirect("image_tools:gallery", doc_pk=doc.pk)
    img = images[index]
    technical = any(h in (img["caption"] + " " + img["context"]).lower() for h in TECHNICAL_HINTS)
    ai_ok, ai_msg = image_service.get_image_provider().available()
    return render(request, "image_tools/editor.html", {"doc": doc, "version": v, "img": img, "index": index,
                                                       "technical": technical, "ai_ok": ai_ok, "ai_msg": ai_msg})


@login_required
@require_POST
def preview(request, doc_pk, index):
    try:
        doc, v = _docx_version(request, doc_pk)
        data = _replacement(request) or image_service.get_image_bytes(v.file.path, index)
        out, fmt, warnings = image_service.process_image(data, _read_ops(request))
    except DocuCraftError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    import io
    with Image.open(io.BytesIO(out)) as im:
        w, h = im.size
    show_fmt = fmt if fmt in ("PNG", "JPEG", "GIF", "WEBP") else "PNG"
    if show_fmt != fmt:
        with Image.open(io.BytesIO(out)) as im:
            buf = io.BytesIO()
            im.save(buf, "PNG")
            shown = buf.getvalue()
    else:
        shown = out
    return JsonResponse({"ok": True, "src": f"data:image/{show_fmt.lower()};base64,{base64.b64encode(shown).decode()}",
                         "width": w, "height": h, "bytes": len(out), "format": fmt, "warnings": warnings})


@login_required
@require_POST
def apply(request, doc_pk, index):
    try:
        doc, v = _docx_version(request, doc_pk)
        replacement = _replacement(request)
    except DocuCraftError as exc:
        messages.error(request, str(exc))
        return redirect("image_tools:editor", doc_pk=doc_pk, index=index)
    if replacement and request.POST.get("confirm_replace") != "1":
        messages.error(request, "Confirm that the new image should replace the original before applying.")
        return redirect("image_tools:editor", doc_pk=doc_pk, index=index)
    options = {"index": index, "ops": _read_ops(request), "caption": request.POST.get("caption"),
               "alignment": request.POST.get("alignment") or None, "location": request.POST.get("location", "")}
    try:
        width = float(request.POST.get("width_in") or 0)
        if 0.3 <= width <= 12:
            options["width_in"] = width
    except ValueError:
        pass
    if replacement:
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        name = default_storage.save(f"temporary/{user_subdir(request.user.id, 'uploads')}/{internal_name('.img')}",
                                    ContentFile(replacement))
        options["replacement_path"] = default_storage.path(name)
    return launch(request, doc, "image_edit", options, source_version=v)


@login_required
@require_POST
def ai_edit(request, doc_pk, index):
    """Optional AI image editing; requires explicit approval and a configured provider."""
    if request.POST.get("approve") != "1":
        return JsonResponse({"ok": False, "error": "Approve AI editing before running it."}, status=400)
    provider = image_service.get_image_provider()
    try:
        doc, v = _docx_version(request, doc_pk)
        data = image_service.get_image_bytes(v.file.path, index)
        out = provider.edit(data, request.POST.get("instruction", "")[:500])
    except DocuCraftError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "src": "data:image/png;base64," + base64.b64encode(out).decode()})
