"""Low-level helpers for walking and classifying python-docx structures."""
import re

from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

MONO_FONTS = {"courier", "courier new", "consolas", "menlo", "monaco", "source code pro",
              "lucida console", "dejavu sans mono", "liberation mono", "fira code", "jetbrains mono"}
CODE_STYLE_HINTS = ("code", "preformatted", "source", "macro text", "console", "verbatim")
CAPTION_RE = re.compile(r"^\s*(figure|fig\.|table|listing|chart|image)\s*\d+", re.I)
CODE_LINE_RE = re.compile(
    r"^\s*(#include|import |from \S+ import|def |class |public |private |protected |static |"
    r"int |void |for\s*\(|while\s*\(|if\s*\(|return |console\.|printf|cout|System\.out|\$ |>>> |"
    r"sudo |pip |npm |git |SELECT |INSERT |UPDATE |CREATE |\}|\{|//|/\*|\*/)"
)


def iter_block_items(parent):
    """Yield Paragraph and Table objects in document order."""
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        parent_elm = parent._element
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def iter_all_paragraphs(doc):
    """Every paragraph in body order, descending into table cells (deduplicating merged cells)."""
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            yield block, None
        else:
            seen = set()
            for row in block.rows:
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    for p in cell.paragraphs:
                        yield p, block


def _run_font_name(run):
    if run.font and run.font.name:
        return run.font.name
    rpr = run._element.rPr
    if rpr is not None and rpr.rFonts is not None:
        return rpr.rFonts.get(qn("w:ascii"))
    return None


def is_monospaced(paragraph):
    runs = [r for r in paragraph.runs if r.text.strip()]
    if not runs:
        return False
    style_font = None
    try:
        style_font = paragraph.style.font.name
    except Exception:
        pass
    mono = 0
    for r in runs:
        name = (_run_font_name(r) or style_font or "").lower()
        if name in MONO_FONTS or "mono" in name or "courier" in name:
            mono += 1
    return mono == len(runs)


def has_hyperlink(paragraph):
    return bool(paragraph._p.findall(qn("w:hyperlink"))) or "HYPERLINK" in paragraph._p.xml


def has_drawing(paragraph):
    xml = paragraph._p.xml
    return "<w:drawing" in xml or "<w:pict" in xml or "<w:object" in xml


def has_field_or_math(paragraph):
    xml = paragraph._p.xml
    return "<m:oMath" in xml or "<w:fldChar" in xml or "<w:instrText" in xml


def has_page_break(paragraph):
    return 'w:type="page"' in paragraph._p.xml


def style_name(paragraph):
    try:
        return paragraph.style.name or ""
    except Exception:
        return ""


def heading_level(paragraph):
    name = style_name(paragraph).lower()
    if name == "title":
        return 0
    m = re.match(r"heading\s*(\d)", name)
    if m:
        return int(m.group(1))
    # outline level set directly on the paragraph
    ppr = paragraph._p.pPr
    if ppr is not None:
        ol = ppr.find(qn("w:outlineLvl"))
        if ol is not None:
            try:
                return int(ol.get(qn("w:val"))) + 1
            except (TypeError, ValueError):
                pass
    return None


def is_list_item(paragraph):
    ppr = paragraph._p.pPr
    if ppr is not None and ppr.numPr is not None:
        return True
    return "list" in style_name(paragraph).lower()


def classify_paragraph(paragraph):
    """Return one of: empty, heading, title, code, caption, list, paragraph."""
    text = paragraph.text
    if not text.strip():
        return "empty"
    sname = style_name(paragraph).lower()
    lvl = heading_level(paragraph)
    if lvl == 0:
        return "title"
    if lvl is not None:
        return "heading"
    if any(h in sname for h in CODE_STYLE_HINTS) or is_monospaced(paragraph):
        return "code"
    if "caption" in sname or CAPTION_RE.match(text):
        return "caption"
    # Heuristic for code pasted in a proportional font
    if CODE_LINE_RE.match(text) and (text.rstrip().endswith((";", "{", "}", ":", ")")) or text.startswith(("$ ", ">>> ", "#include", "import "))):
        return "code"
    if is_list_item(paragraph):
        return "list"
    return "paragraph"


def set_paragraph_text(paragraph, new_text):
    """Replace a paragraph's text while keeping paragraph properties and first-run formatting.

    Only used on paragraphs without hyperlinks, drawings, fields or equations
    (those are preserved untouched by the rewrite engine).
    """
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(new_text)
        return
    # Keep run that carries most text so the dominant formatting survives.
    main = max(runs, key=lambda r: len(r.text))
    for r in runs:
        if r is not main:
            r._element.getparent().remove(r._element)
    main.text = new_text
