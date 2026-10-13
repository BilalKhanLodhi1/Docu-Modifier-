"""Template formatting job."""
from pathlib import Path

from apps.documents.jobs import save_version, source_path, task
from services.docx_writer import apply_template
from services.exceptions import DocuCraftError
from services.storage import temp_workdir

from .models import DocumentTemplate


def build_metadata(job):
    meta = dict(job.options.get("metadata") or {})
    logo = job.options.get("logo_path")
    tpl = DocumentTemplate.objects.filter(pk=job.options.get("template_id")).first()
    if not logo and tpl and tpl.logo:
        logo = tpl.logo.path
    if logo and Path(logo).exists():
        meta["logo_path"] = logo
    return meta, tpl


def run_format(job, src, dst):
    meta, tpl = build_metadata(job)
    if tpl is None:
        raise DocuCraftError("The selected template no longer exists.")
    cfg = tpl.merged()
    overrides = job.options.get("overrides") or {}
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    scope = job.options.get("scope_ids") or None
    return apply_template(src, dst, cfg, meta, scope_ids=scope,
                          include_cover=job.options.get("include_cover"), include_toc=job.options.get("include_toc"))


@task("format")
def format_task(job, progress):
    src, version = source_path(job)
    if version.file_type != "docx":
        raise DocuCraftError("Templates can be applied to Word documents. Convert this PDF to Word first.")
    progress("formatting", 30, "Applying template styles")
    with temp_workdir() as tmp:
        dst = tmp / "formatted.docx"
        info = run_format(job, src, dst)
        progress("preparing", 90, "Saving new version")
        tpl_name = job.options.get("template_name", "template")
        v = save_version(job.document, dst, "docx", "format", f"Applied {tpl_name}", parent=version, details=info)
    job.output_version = v
    job.save(update_fields=["output_version"])
    job.document.active_template_id = job.options.get("template_id")
    job.document.save(update_fields=["active_template"])
    return {"message": f"Template applied. Saved as version {v.version_number}."}
