"""Low-level helpers for walking and classifying python-docx structures."""
import copy
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


def _run_signature(run):
    """The visible character formatting of a run, ignoring noise such as language tags."""
    f = run.font
    try:
        color = str(f.color.rgb) if f.color is not None and f.color.type is not None else ""
    except (AttributeError, ValueError):
        color = ""
    return (bool(run.bold), bool(run.italic), bool(run.underline), bool(f.strike), bool(f.superscript),
            bool(f.subscript), str(f.highlight_color or ""), color, f.name or "")


def set_paragraph_text(paragraph, new_text):
    """Replace a paragraph's text, keeping paragraph properties and inline formatting.

    The run style used for most of the text becomes the base. Words that were styled differently
    (bold, italic, code font, superscript...) keep that style wherever the same text still appears
    in the new wording. Only used on paragraphs without hyperlinks, drawings, fields or equations
    (those are preserved untouched by the rewrite engine).
    """
    from docx.text.run import Run
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(new_text)
        return
    # Merge neighbouring runs with identical formatting; Word often splits one word into several runs.
    groups = []
    for r in runs:
        sig = _run_signature(r)
        if groups and groups[-1][0] == sig:
            groups[-1][1] += r.text
        else:
            groups.append([sig, r.text, r])
    weight = {}
    for sig, text, _ in groups:
        weight[sig] = weight.get(sig, 0) + len(text)
    base_sig = max(weight, key=weight.get)
    base_run = next(r for sig, _, r in groups if sig == base_sig)

    # Find each specially formatted phrase in the new text, in order where possible.
    old_text = "".join(text for _, text, _ in groups)
    spans, cursor, offset = [], 0, 0
    for sig, text, run in groups:
        phrase = text.strip()
        start_in_old = offset + (len(text) - len(text.lstrip()))
        offset += len(text)
        if sig == base_sig or not phrase:
            continue
        if len(phrase) < 2:
            # Single characters only for super/subscripts (note markers, formulas), placed by position.
            if not (sig[4] or sig[5]):
                continue
            hits = [i for i in range(len(new_text)) if new_text.startswith(phrase, i)]
            if not hits:
                continue
            target = start_in_old / max(1, len(old_text)) * len(new_text)
            at = min(hits, key=lambda i: abs(i - target))
        else:
            at = new_text.find(phrase, cursor)
            if at < 0:
                at = new_text.find(phrase)
        if at < 0 or any(a < at + len(phrase) and at < b for a, b, _ in spans):
            continue
        spans.append((at, at + len(phrase), run))
        cursor = at + len(phrase)
    spans.sort(key=lambda x: x[0])

    pieces, pos = [], 0
    for a, b, run in spans:
        if a > pos:
            pieces.append((new_text[pos:a], base_run))
        pieces.append((new_text[a:b], run))
        pos = b
    if pos < len(new_text) or not pieces:
        pieces.append((new_text[pos:], base_run))

    p_el = paragraph._p
    first_r = runs[0]._r
    insert_at = list(p_el).index(first_r)
    templates = {id(r): copy.deepcopy(r._r) for _, _, r in groups}
    for r in runs:
        p_el.remove(r._r)
    for offset, (text, src) in enumerate(pieces):
        r_el = copy.deepcopy(templates[id(src)])
        for child in list(r_el):
            if child.tag != qn("w:rPr"):
                r_el.remove(child)
        p_el.insert(insert_at + offset, r_el)
        Run(r_el, paragraph).text = text