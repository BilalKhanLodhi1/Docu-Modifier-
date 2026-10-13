"""Full-document AI rewriting that preserves DOCX structure.

Workflow: collect rewritable units (paragraphs, headings, list items, captions,
table-cell text) in document order -> chunk them -> send each chunk as
structured JSON -> validate every returned section -> write the accepted text
back into a COPY of the original DOCX, paragraph by paragraph.

Code, equations, fields, hyperlink paragraphs and image paragraphs are never
sent to the model; they are copied through untouched.
"""
import json
import logging
import re

import docx

from .ai_provider import get_provider
from .docx_utils import (classify_paragraph, has_drawing, has_field_or_math,
                         has_hyperlink, iter_all_paragraphs, set_paragraph_text)
from .document_validator import missing_tokens
from .exceptions import AIProviderError, DocuCraftError
from .prompts import SYSTEM_PROMPT, build_user_message

log = logging.getLogger("docucraft.rewrite")

REWRITABLE = {"paragraph", "heading", "title", "list", "caption"}


def collect_units(document):
    """Return every paragraph as a unit with a stable id and an eligibility decision."""
    units = []
    current_heading = ""
    for idx, (p, table) in enumerate(iter_all_paragraphs(document)):
        kind = classify_paragraph(p)
        text = p.text
        reason = ""
        if kind == "empty":
            reason = "empty"
        elif kind == "code":
            reason = "code is preserved"
        elif has_drawing(p):
            reason = "contains an image"
        elif has_field_or_math(p):
            reason = "contains an equation or field"
        elif has_hyperlink(p):
            reason = "contains a hyperlink"
        elif len(text.strip()) < 4:
            reason = "too short"
        elif table is not None and len(text.split()) < 4:
            reason = "short table cell"
        if kind in ("heading", "title"):
            current_heading = text.strip()
        units.append({
            "id": f"p{idx}",
            "kind": "table-cell" if table is not None and kind == "paragraph" else kind,
            "text": text,
            "eligible": not reason and kind in REWRITABLE,
            "reason": reason,
            "heading": current_heading,
            "paragraph": p,
        })
    return units


def chunk_units(units, max_chars):
    """Group eligible units into ordered batches under max_chars (never splits a unit)."""
    batches, batch, size = [], [], 0
    for u in units:
        if not u["eligible"]:
            continue
        n = len(u["text"]) + 60
        if batch and size + n > max_chars:
            batches.append(batch)
            batch, size = [], 0
        batch.append(u)
        size += n
    if batch:
        batches.append(batch)
    return batches


def parse_ai_json(raw):
    """Parse the model reply, tolerating code fences or stray prose around the JSON."""
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in response")
        data = json.loads(raw[start:end + 1])
    if isinstance(data, list):
        data = {"sections": data}
    sections = data.get("sections")
    if not isinstance(sections, list):
        raise ValueError("response has no 'sections' list")
    out = {}
    for s in sections:
        if isinstance(s, dict) and isinstance(s.get("id"), str) and isinstance(s.get("text"), str):
            out[s["id"]] = {"text": s["text"].strip(), "flag": str(s.get("flag") or "").strip()}
    return out


_LENGTH_LIMITS = {"concise": (0.2, 1.6), "grammar": (0.6, 1.6)}


def validate_rewrite(original, rewritten, kind, mode):
    """Return (ok, note). Rejects lost facts, suspicious length changes and junk."""
    if not rewritten.strip():
        return False, "The model returned empty text."
    lost = missing_tokens(original, rewritten)
    if lost:
        return False, "Kept original: the rewrite changed or dropped " + ", ".join(lost[:6])
    lo, hi = _LENGTH_LIMITS.get(mode, (0.35, 2.2))
    ratio = len(rewritten) / max(1, len(original))
    if len(original) > 40 and ratio < lo:
        return False, "Kept original: the rewrite looked like it removed content."
    if len(original) > 40 and ratio > hi:
        return False, "Kept original: the rewrite added more text than expected."
    if kind in ("heading", "title") and len(rewritten) > max(120, len(original) * 2.5):
        return False, "Kept original: the heading was expanded into prose."
    if rewritten.lstrip().startswith(("{", "```")):
        return False, "Kept original: the model returned formatting instead of text."
    return True, ""


def rewrite_document(src_path, mode="professional", custom_instructions="", audience="",
                     provider=None, max_chars=6000, progress=None):
    """Run the AI over the whole document. Returns a comparison list; does not write files.

    `progress(stage, percent, message)` is called as work advances.
    """
    provider = provider or get_provider()
    progress = progress or (lambda *a, **k: None)
    progress("extracting", 5, "Reading document structure")
    document = docx.Document(str(src_path))
    units = collect_units(document)
    batches = chunk_units(units, max_chars)
    if not batches:
        raise DocuCraftError("No rewritable text was found. The document may contain only code, images or tables.")

    results = {}
    for i, batch in enumerate(batches, start=1):
        pct = 10 + int(70 * (i - 1) / len(batches))
        progress("rewriting", pct, f"Rewriting part {i} of {len(batches)}")
        message = build_user_message(batch, mode, custom_instructions, audience, batch[0]["heading"])
        parsed = None
        last_error = None
        for attempt in range(2):
            raw = provider.complete(SYSTEM_PROMPT, message)
            try:
                parsed = parse_ai_json(raw)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                log.warning("Unparseable AI response on batch %s attempt %s: %s", i, attempt + 1, exc)
        if parsed is None:
            raise AIProviderError(f"The AI returned an unreadable response for part {i} of {len(batches)}. "
                                  "Try again or choose a different model.") from last_error
        results.update({u["id"]: parsed.get(u["id"]) for u in batch})

    progress("validating", 85, "Checking names, numbers and references")
    comparison = []
    for u in units:
        if u["kind"] == "empty":
            continue
        entry = {"id": u["id"], "kind": u["kind"], "original": u["text"], "rewritten": u["text"],
                 "status": "preserved", "note": u["reason"], "flag": ""}
        if u["eligible"]:
            r = results.get(u["id"])
            if r is None:
                entry.update(status="reverted", note="Kept original: the model skipped this section.")
            else:
                ok, note = validate_rewrite(u["text"], r["text"], u["kind"], mode)
                entry["flag"] = r["flag"]
                if ok:
                    same = _normalize(r["text"]) == _normalize(u["text"])
                    entry.update(rewritten=r["text"], status="unchanged" if same else "changed", note="")
                else:
                    entry.update(status="reverted", note=note)
        comparison.append(entry)
    return comparison


def _normalize(s):
    return re.sub(r"\s+", " ", s).strip()


def apply_rewrites(src_path, dst_path, accepted):
    """Write accepted rewrites {unit_id: text} into a copy of src_path saved at dst_path."""
    document = docx.Document(str(src_path))
    units = collect_units(document)
    applied = 0
    for u in units:
        new = accepted.get(u["id"])
        if new is None or not u["eligible"]:
            continue
        if _normalize(new) != _normalize(u["text"]):
            set_paragraph_text(u["paragraph"], new)
            applied += 1
    document.save(str(dst_path))
    return applied


def summarize(comparison):
    s = {"changed": 0, "unchanged": 0, "preserved": 0, "reverted": 0, "flagged": 0}
    for c in comparison:
        s[c["status"]] = s.get(c["status"], 0) + 1
        if c.get("flag"):
            s["flagged"] += 1
    return s
