"""Image edit job: process an image and reinsert it into a copy of the document."""
from pathlib import Path

from django.conf import settings

from django.core.files.base import ContentFile

from apps.documents.jobs import save_version, source_path, task
from services import image_service
from services.exceptions import DocuCraftError
from services.storage import temp_workdir

from .models import DocumentImage


@task("image_edit")
def image_edit_task(job, progress):
    src, version = source_path(job)
    opts = job.options
    index = int(opts["index"])
    progress("enhancing", 20, "Processing image")
    original = image_service.get_image_bytes(src, index)
    replacement = opts.get("replacement_path")
    if replacement:
        rp = Path(replacement)
        media = Path(settings.MEDIA_ROOT).resolve()
        if not rp.resolve().is_relative_to(media) or not rp.exists():
            raise DocuCraftError("The replacement image is no longer available. Upload it again.")
        new_bytes = rp.read_bytes()
        rp.unlink(missing_ok=True)
        new_bytes, fmt, warnings = image_service.process_image(new_bytes, opts.get("ops") or {})
    else:
        new_bytes, fmt, warnings = image_service.process_image(original, opts.get("ops") or {})
    progress("formatting", 60, "Placing the image back into the document")
    with temp_workdir() as tmp:
        dst = tmp / "edited.docx"
        info = image_service.replace_image(src, dst, index, new_bytes, width_in=opts.get("width_in"),
                                           alignment=opts.get("alignment") or None,
                                           caption=opts.get("caption"))
        v = save_version(job.document, dst, "docx", "image_edit", f"Edited image {index + 1}", parent=version,
                         details={"image_index": index, **info})
    rec = DocumentImage(version=version, result_version=v, image_index=index, image_format=info["format"],
                        width=info["width_px"], height=info["height_px"], caption=opts.get("caption") or "",
                        location=opts.get("location", "")[:200],
                        operations={k: v2 for k, v2 in (opts.get("ops") or {}).items()})
    rec.original_image.save(f"img{index}_orig", ContentFile(original), save=False)
    rec.processed_image.save(f"img{index}_new.{info['format'].lower()}", ContentFile(new_bytes), save=False)
    rec.save()
    job.output_version = v
    job.result = {"warnings": warnings}
    job.save(update_fields=["output_version", "result"])
    return {"message": f"Image updated. Saved as version {v.version_number}."}
