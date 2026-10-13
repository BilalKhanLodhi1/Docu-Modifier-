"""AI rewrite job."""
from django.conf import settings

from apps.accounts.models import UserPreference
from apps.documents.jobs import add_output, source_path, task
from services.ai_provider import get_provider
from services.exceptions import DocuCraftError
from services.rewrite_service import apply_rewrites, rewrite_document, summarize
from services.storage import temp_workdir


def provider_for(user):
    pref = UserPreference.for_user(user)
    provider = get_provider(pref.ai_provider or None)
    if provider.is_cloud and not pref.allow_cloud_ai:
        raise DocuCraftError("Your AI provider is a cloud service, but you have not allowed documents to be "
                             "sent to it. Enable cloud AI in Settings, or switch to the local Ollama provider.")
    return provider


def run_rewrite(job, progress, src=None):
    src_path, version = (src, None) if src else source_path(job)
    if str(src_path).lower().endswith(".pdf"):
        raise DocuCraftError("AI rewriting works on Word documents. Convert this PDF to Word first.")
    opts = job.options
    comparison = rewrite_document(
        src_path, mode=opts.get("mode", "professional"), custom_instructions=opts.get("custom_instructions", ""),
        audience=opts.get("audience", ""), provider=provider_for(job.user), max_chars=settings.AI_CHUNK_CHARS,
        progress=progress)
    return comparison


@task("rewrite")
def rewrite_task(job, progress):
    comparison = run_rewrite(job, progress)
    src_path, version = source_path(job)
    progress("formatting", 90, "Building the revised document")
    accepted = {c["id"]: c["rewritten"] for c in comparison if c["status"] == "changed"}
    with temp_workdir() as tmp:
        draft = tmp / f"{job.document.stem}_rewritten.docx"
        apply_rewrites(src_path, draft, accepted)
        progress("preparing", 96, "Preparing download")
        add_output(job, draft, "Rewritten draft (all validated changes)", filename=draft.name)
    stats = summarize(comparison)
    job.result = {"comparison": comparison, "stats": stats}
    job.save(update_fields=["result"])
    return {"message": f"{stats['changed']} sections rewritten, {stats['reverted']} kept original after validation. Review before saving."}
