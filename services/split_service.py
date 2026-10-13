"""Split PDFs by pages and DOCX files by structure.

PDF splitting is page-based (pypdf). DOCX splitting is structure-aware: each
output is a copy of the source with body elements outside the chosen section
removed, so styles, numbering, headers, footers and images survive.
"""
import re
import zipfile
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, PdfWriter

from .docx_utils import heading_level, style_name
from .exceptions import DocuCraftError

TASK_RE = re.compile(r"^\s*(task|chapter|exercise|question|part|lab|section|activity|problem)\s*[-#:.]?\s*(\d+|[ivxlc]+)\b", re.I)


# ----------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------
def parse_ranges(spec, page_count):
    """'1-3, 4-6, 9' -> [(1,3),(4,6),(9,9)] (1-based inclusive), validated."""
    if not spec or not spec.strip():
        raise DocuCraftError("Enter at least one page range, for example 1-3, 4-6.")
    ranges = []
    for part in re.split(r"[;,]", spec):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:[-\u2013]\s*(\d+|end))?", part, re.I)
        if not m:
            raise DocuCraftError(f"'{part}' is not a valid page range. Use forms like 2 or 4-7.")
        a = int(m.group(1))
        b = page_count if (m.group(2) or "").lower() == "end" else int(m.group(2) or a)
        if a < 1 or b > page_count or a > b:
            raise DocuCraftError(f"Range {part} is outside the document (pages 1-{page_count}).")
        ranges.append((a, b))
    return ranges


def plan_pdf_split(path, method, ranges_spec="", pages_per_file=1):
    reader = PdfReader(str(path))
    n = len(reader.pages)
    if method == "ranges":
        ranges = parse_ranges(ranges_spec, n)
    elif method == "pages":
        ranges = [(i, i) for i in range(1, n + 1)]
    elif method == "every_n":
        k = max(1, int(pages_per_file or 1))
        ranges = [(i, min(i + k - 1, n)) for i in range(1, n + 1, k)]
    else:
        raise DocuCraftError("That split method is not available for PDFs.")
    return [{"label": f"Pages {a}-{b}" if a != b else f"Page {a}", "start": a, "end": b} for a, b in ranges]


def split_pdf(path, parts, out_dir, base_name):
    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    outputs = []
    for i, part in enumerate(parts, start=1):
        writer = PdfWriter()
        for pg in range(part["start"] - 1, part["end"]):
            writer.add_page(reader.pages[pg])
        try:
            writer.add_metadata({k: str(v) for k, v in meta.items() if isinstance(k, str)})
        except Exception:
            pass
        name = _safe_part_name(part.get("filename") or f"{base_name}_{part['label']}", ".pdf", i)
        dst = Path(out_dir) / name
        with open(dst, "wb") as fh:
            writer.write(fh)
        outputs.append((dst, part["label"]))
    return outputs


# ----------------------------------------------------------------------------
# DOCX
# ----------------------------------------------------------------------------
def _body_children(document):
    body = document.element.body
    return [c for c in body.iterchildren() if c.tag != qn("w:sectPr")]


def plan_docx_split(path, method="heading", level=1):
    """Return proposed sections: [{label, start, end (exclusive), preview}] over body element indices."""
    document = docx.Document(str(path))
    children = _body_children(document)
    starts = []
    for i, el in enumerate(children):
        if el.tag != qn("w:p"):
            continue
        p = Paragraph(el, document._body)
        text = p.text.strip()
        if not text:
            continue
        if method == "heading":
            lvl = heading_level(p)
            if lvl is not None and 1 <= lvl <= int(level):
                starts.append((i, text))
        elif method == "tasks":
            bold = p.runs and all(r.bold for r in p.runs if r.text.strip())
            if TASK_RE.match(text) and (heading_level(p) is not None or bold or len(text) < 90):
                starts.append((i, text))
        else:
            raise DocuCraftError("That split method is not available for Word documents.")
    if not starts:
        what = "headings" if method == "heading" else "task, chapter or exercise titles"
        raise DocuCraftError(f"No {what} were found to split on. Apply Heading styles in Word or choose another method.")
    sections = []
    if starts[0][0] > 0 and any(_has_content(children[j]) for j in range(0, starts[0][0])):
        sections.append({"label": "Front matter", "start": 0, "end": starts[0][0]})
    for k, (i, text) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(children)
        sections.append({"label": text[:80], "start": i, "end": end})
    for s in sections:
        words = 0
        for el in children[s["start"]:s["end"]]:
            words += len("".join(t.text or "" for t in el.iter(qn("w:t"))).split())
        s["words"] = words
        s["blocks"] = s["end"] - s["start"]
        s["images"] = sum(1 for el in children[s["start"]:s["end"]] for _ in el.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"))
    return sections


def _has_content(el):
    return bool("".join(t.text or "" for t in el.iter(qn("w:t"))).strip()) or "<w:drawing" in _xml(el)


def _xml(el):
    from lxml import etree
    return etree.tostring(el, encoding="unicode")


def split_docx(path, sections, out_dir, base_name, combine=False):
    """Create one DOCX per section (or one combined DOCX of all selected sections)."""
    groups = [sections] if combine else [[s] for s in sections]
    outputs = []
    for i, group in enumerate(groups, start=1):
        document = docx.Document(str(path))
        children = _body_children(document)
        keep = set()
        for s in group:
            keep.update(range(s["start"], s["end"]))
        for idx, el in enumerate(children):
            if idx not in keep:
                el.getparent().remove(el)
        # Remove a leading page break so parts don't start with a blank page.
        body = document.element.body
        first = body[0] if len(body) else None
        if first is not None and first.tag == qn("w:p"):
            ppr = first.find(qn("w:pPr"))
            if ppr is not None:
                for pb in ppr.findall(qn("w:pageBreakBefore")):
                    ppr.remove(pb)
        label = group[0].get("filename") or (group[0]["label"] if not combine else "selected_sections")
        name = _safe_part_name(label if group[0].get("filename") else f"{base_name}_{label}", ".docx", i)
        dst = Path(out_dir) / name
        document.save(str(dst))
        outputs.append((dst, group[0]["label"] if not combine else f"{len(group)} sections combined"))
    return outputs


def _safe_part_name(name, suffix, i):
    stem = Path(name).stem if name.lower().endswith(suffix) else name
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_")[:70] or "part"
    return f"{i:02d}_{stem}{suffix}"


def zip_outputs(paths, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=Path(p).name)
    return zip_path
