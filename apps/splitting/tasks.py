"""Split job."""
from apps.documents.jobs import add_output, source_path, task
from services import split_service
from services.storage import temp_workdir


@task("split")
def split_task(job, progress):
    src, version = source_path(job)
    opts = job.options
    parts = opts["parts"]
    base = job.document.stem[:40]
    progress("splitting", 20, f"Creating {len(parts)} file(s)")
    with temp_workdir() as tmp:
        if version.file_type == "pdf":
            outputs = split_service.split_pdf(src, parts, tmp, base)
        else:
            outputs = split_service.split_docx(src, parts, tmp, base, combine=opts.get("combine", False))
        progress("preparing", 80, "Preparing downloads")
        for path, label in outputs:
            add_output(job, path, label)
        if len(outputs) > 1:
            z = split_service.zip_outputs([p for p, _ in outputs], tmp / f"{base}_parts.zip")
            add_output(job, z, "All parts (ZIP)", file_type="zip")
    return {"message": f"Created {len(outputs)} file(s)."}
