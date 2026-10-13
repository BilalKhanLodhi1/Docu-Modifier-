"""Combined workflow: run several operations in order on intermediate copies.

Each step reads the previous step's output. If a step fails, every earlier
successful step has already been saved as its own version, so nothing is lost.
"""
from apps.documents.jobs import add_output, save_version, source_path, task
from services import conversion_service
from services.exceptions import DocuCraftError
from services.rewrite_service import apply_rewrites, summarize
from services.storage import temp_workdir

PIPELINE_ORDER = ["rewrite", "format", "export_pdf"]


@task("pipeline")
def pipeline_task(job, progress):
    from apps.rewriting.tasks import run_rewrite
    from apps.templates_manager.tasks import run_format

    src, version = source_path(job)
    if version.file_type != "docx":
        raise DocuCraftError("The combined workflow starts from a Word document. Convert the PDF to Word first.")
    steps = [s for s in PIPELINE_ORDER if s in job.options.get("steps", [])]
    if not steps:
        raise DocuCraftError("Select at least one step.")
    done = []
    current_path, current_version = src, version
    with temp_workdir() as tmp:
        for n, step in enumerate(steps, start=1):
            base = int(90 * (n - 1) / len(steps))
            if step == "rewrite":
                def p(stage, pct, msg=""):
                    progress(stage, base + pct * 0.9 / len(steps), f"Step {n}: {msg}")
                comparison = run_rewrite(job, p, src=current_path)
                accepted = {c["id"]: c["rewritten"] for c in comparison if c["status"] == "changed"}
                out = tmp / f"step{n}_rewrite.docx"
                apply_rewrites(current_path, out, accepted)
                stats = summarize(comparison)
                current_version = save_version(job.document, out, "docx", "rewrite",
                                               f"AI rewrite ({stats['changed']} sections)", parent=current_version,
                                               details={"stats": stats})
                job.result = {**job.result, "comparison": comparison, "stats": stats}
                job.save(update_fields=["result"])
                current_path = out
            elif step == "format":
                progress("formatting", base + 5, f"Step {n}: applying template")
                out = tmp / f"step{n}_format.docx"
                run_format(job, current_path, out)
                current_version = save_version(job.document, out, "docx", "format",
                                               f"Applied {job.options.get('template_name', 'template')}",
                                               parent=current_version)
                current_path = out
            elif step == "export_pdf":
                progress("converting", base + 5, f"Step {n}: exporting PDF")
                out = tmp / f"{job.document.stem}.pdf"
                conversion_service.docx_to_pdf(current_path, out)
                add_output(job, out, f"PDF of version {current_version.version_number}")
            done.append(step)
        progress("preparing", 96, "Preparing downloads")
        add_output(job, current_path, f"Word document (version {current_version.version_number})",
                   filename=f"{job.document.stem}_final.docx")
    job.output_version = current_version if current_version != version else None
    job.save(update_fields=["output_version"])
    return {"message": f"Completed {len(done)} step(s): {', '.join(done)}."}
