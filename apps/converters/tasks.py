"""Conversion jobs."""
from apps.documents.jobs import add_output, save_version, source_path, task
from services import conversion_service
from services.exceptions import DocuCraftError
from services.storage import temp_workdir


@task("convert_docx_pdf")
def docx_to_pdf_task(job, progress):
    src, version = source_path(job)
    if version.file_type != "docx":
        raise DocuCraftError("Choose a Word version to convert to PDF.")
    progress("converting", 30, "Converting with LibreOffice")
    with temp_workdir() as tmp:
        dst = tmp / f"{job.document.stem}.pdf"
        conversion_service.docx_to_pdf(src, dst)
        progress("preparing", 90, "Preparing download")
        add_output(job, dst, f"PDF of version {version.version_number}")
    return {"message": "Word document converted to PDF.",
            "warnings": ["Fonts not installed on the server are substituted. Check the PDF before sharing."]}


@task("convert_pdf_docx")
def pdf_to_docx_task(job, progress):
    src, version = source_path(job)
    if version.file_type != "pdf":
        raise DocuCraftError("Choose a PDF version to convert to Word.")
    progress("converting", 10, "Analysing PDF")
    with temp_workdir() as tmp:
        dst = tmp / f"{job.document.stem}.docx"
        summary = conversion_service.pdf_to_docx(src, dst, ocr=job.options.get("ocr", "auto"),
                                                 ocr_lang=job.options.get("ocr_lang", "eng"), progress=progress)
        progress("preparing", 92, "Saving editable Word version")
        v = save_version(job.document, dst, "docx", "convert_pdf_docx", f"Converted to Word ({summary['method']})",
                         parent=version, details=summary)
        add_output(job, dst, "Editable Word document")
    job.output_version = v
    job.save(update_fields=["output_version"])
    return {"message": f"Converted {summary['pages']} page(s) using {summary['method']}.",
            "warnings": summary["warnings"], "method": summary["method"]}
