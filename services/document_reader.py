"""Inspect DOCX and PDF documents without modifying them."""
import logging
import zipfile
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .docx_utils import (classify_paragraph, has_hyperlink, heading_level,
                         iter_all_paragraphs, iter_block_items)
from .exceptions import UnsupportedFileError

log = logging.getLogger("docucraft.reader")

SCANNED_CHARS_PER_PAGE = 25


def inspect_docx(path):
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise UnsupportedFileError("The Word document could not be opened. It may be corrupted.") from exc

    counts = {"paragraph": 0, "heading": 0, "title": 0, "code": 0, "caption": 0, "list": 0, "empty": 0}
    words = 0
    hyperlinks = 0
    page_breaks = 0
    outline = []
    for p, table in iter_all_paragraphs(document):
        kind = classify_paragraph(p)
        counts[kind] = counts.get(kind, 0) + 1
        words += len(p.text.split())
        if has_hyperlink(p):
            hyperlinks += 1
        if 'w:type="page"' in p._p.xml:
            page_breaks += 1
        if table is None and kind in ("heading", "title"):
            outline.append({"level": heading_level(p) or 0, "text": p.text.strip()[:140]})

    tables = sum(1 for b in iter_block_items(document) if not isinstance(b, Paragraph))
    images = len(document.inline_shapes)
    body_xml = document.element.body.xml
    anchored = body_xml.count("<wp:anchor")
    sec = document.sections[0]
    has_header = any(any(p.text.strip() for p in s.header.paragraphs) for s in document.sections)
    has_footer = any(any(p.text.strip() for p in s.footer.paragraphs) or "PAGE" in s.footer._element.xml
                     for s in document.sections)

    page_count = None
    try:
        with zipfile.ZipFile(path) as zf:
            if "docProps/app.xml" in zf.namelist():
                import re
                m = re.search(rb"<Pages>(\d+)</Pages>", zf.read("docProps/app.xml"))
                if m:
                    page_count = int(m.group(1))
    except Exception:
        pass

    def mm(v):
        return round(v.mm, 1) if v is not None else None

    return {
        "type": "docx",
        "page_count": page_count,
        "word_count": words,
        "block_counts": counts,
        "tables": tables,
        "images": images + anchored,
        "hyperlinks": hyperlinks,
        "page_breaks": page_breaks,
        "has_header": has_header,
        "has_footer": has_footer,
        "sections": len(document.sections),
        "page_width_mm": mm(sec.page_width),
        "page_height_mm": mm(sec.page_height),
        "margins_mm": {"top": mm(sec.top_margin), "bottom": mm(sec.bottom_margin),
                       "left": mm(sec.left_margin), "right": mm(sec.right_margin)},
        "outline": outline[:60],
        "title": (document.core_properties.title or "").strip(),
        "author": (document.core_properties.author or "").strip(),
    }


def inspect_pdf(path):
    import pymupdf
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise UnsupportedFileError("The PDF could not be opened. It may be corrupted.") from exc
    with doc:
        text_chars = 0
        image_pages = 0
        images = 0
        low_text_pages = 0
        multi_column_pages = 0
        for page in doc:
            txt = page.get_text("text")
            text_chars += len(txt.strip())
            imgs = page.get_images(full=True)
            images += len(imgs)
            if imgs:
                image_pages += 1
            if len(txt.strip()) < SCANNED_CHARS_PER_PAGE:
                low_text_pages += 1
            blocks = [b for b in page.get_text("blocks") if b[4].strip()]
            if len(blocks) > 4:
                mid = page.rect.width / 2
                left = sum(1 for b in blocks if b[2] < mid)
                right = sum(1 for b in blocks if b[0] > mid)
                if left >= 2 and right >= 2:
                    multi_column_pages += 1
        meta = doc.metadata or {}
        first = doc[0].rect
        toc = doc.get_toc(simple=True)
        page_count = doc.page_count
        fonts = set()
        for page in doc:
            for f in page.get_fonts():
                fonts.add(f[3])
            if len(fonts) > 40:
                break
    needs_ocr = low_text_pages >= max(1, page_count // 2) and images > 0 or text_chars == 0
    return {
        "type": "pdf",
        "page_count": page_count,
        "text_chars": text_chars,
        "images": images,
        "needs_ocr": needs_ocr,
        "low_text_pages": low_text_pages,
        "multi_column_pages": multi_column_pages,
        "page_width_mm": round(first.width * 25.4 / 72, 1),
        "page_height_mm": round(first.height * 25.4 / 72, 1),
        "title": (meta.get("title") or "").strip(),
        "author": (meta.get("author") or "").strip(),
        "outline": [{"level": lvl, "text": t[:140], "page": pg} for lvl, t, pg in toc[:60]],
        "font_count": len(fonts),
    }


def inspect(path, file_type):
    return inspect_docx(path) if file_type == "docx" else inspect_pdf(path)


def docx_preview_html(path, max_chars=400_000):
    """HTML preview of a DOCX via mammoth. Output is sanitized by the template (|safe only after bleach-free stripping)."""
    import mammoth
    with open(path, "rb") as fh:
        result = mammoth.convert_to_html(fh)
    html = result.value
    if len(html) > max_chars:
        html = html[:max_chars] + "<p><em>Preview truncated. Download the file to see the full document.</em></p>"
    return _sanitize_html(html)


def _sanitize_html(html):
    """Remove scripts, event handlers and javascript: URLs from generated preview HTML."""
    import re
    html = re.sub(r"<\s*(script|style|iframe|object|embed)[^>]*>.*?<\s*/\s*\1\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    html = re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", r'\1="#"', html, flags=re.I)
    return html


def pdf_page_png(path, page_number, zoom=1.3):
    """Render one PDF page (0-based) to PNG bytes for thumbnails."""
    import pymupdf
    with pymupdf.open(str(path)) as doc:
        page_number = max(0, min(page_number, doc.page_count - 1))
        pix = doc[page_number].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")


def extract_text(path, file_type, limit=None):
    if file_type == "docx":
        d = docx.Document(str(path))
        text = "\n".join(p.text for p, _ in iter_all_paragraphs(d))
    else:
        import pymupdf
        with pymupdf.open(str(path)) as doc:
            text = "\n".join(page.get_text("text") for page in doc)
    return text[:limit] if limit else text
