"""File validation and factual-preservation checks."""
import re
import zipfile
from collections import Counter
from pathlib import Path

from .exceptions import UnsupportedFileError

ALLOWED_EXTENSIONS = {".docx", ".pdf"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"


def detect_type(fileobj, filename):
    """Return 'docx' or 'pdf' by checking the extension AND the file signature.

    Raises UnsupportedFileError for anything else, or when the content does
    not match the extension (a renamed file, a corrupted upload).
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError("Only .docx and .pdf files are supported.")
    pos = fileobj.tell() if hasattr(fileobj, "tell") else 0
    fileobj.seek(0)
    head = fileobj.read(8)
    fileobj.seek(0)
    if ext == ".pdf":
        if not head.startswith(b"%PDF-"):
            raise UnsupportedFileError("This file has a .pdf extension but is not a valid PDF.")
        try:
            import pymupdf
            data = fileobj.read()
            fileobj.seek(0)
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if doc.page_count == 0:
                    raise UnsupportedFileError("The PDF has no pages.")
                if doc.needs_pass:
                    raise UnsupportedFileError("Password-protected PDFs are not supported. Remove the password and upload again.")
        except UnsupportedFileError:
            raise
        except Exception:
            raise UnsupportedFileError("The PDF appears to be corrupted and could not be opened.")
        return "pdf"
    # .docx is a ZIP package that must contain word/document.xml
    if not head.startswith(b"PK"):
        raise UnsupportedFileError("This file has a .docx extension but is not a valid Word document.")
    try:
        with zipfile.ZipFile(fileobj) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise UnsupportedFileError("The archive is not a Word document (word/document.xml is missing).")
            total = sum(i.file_size for i in zf.infolist())
            if total > 500 * 1024 * 1024:
                raise UnsupportedFileError("The document expands to an unsafe size and was rejected.")
    except zipfile.BadZipFile:
        raise UnsupportedFileError("The Word document appears to be corrupted.")
    finally:
        fileobj.seek(0)
    if pos:
        fileobj.seek(0)
    return "docx"


def safe_display_name(name, max_len=120):
    """Strip path components and unsafe characters from a user-supplied filename."""
    name = Path(name).name
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    stem = re.sub(r"[^\w\-. ()]+", "_", stem).strip("._ ") or "document"
    return (stem[: max_len - len(suffix)] + suffix)


# ----------------------------------------------------------------------------
# Factual preservation
# ----------------------------------------------------------------------------
_TOKEN_PATTERNS = [
    ("url", r"https?://[^\s)\]>]+"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("citation", r"\[\d+(?:\s*[,\u2013-]\s*\d+)*\]"),
    ("date", r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b"),
    ("number", r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?"),
    ("identifier", r"\b[A-Za-z_]+\w*\(\)|\b[a-z]+_[a-z_0-9]+\b|\b[a-z]+[A-Z]\w*\b"),
    ("formula", r"[A-Za-z0-9)]\s*[=<>\u2264\u2265]\s*[A-Za-z0-9(]"),
]


def protected_tokens(text):
    """Extract tokens that a rewrite must not change (numbers, dates, URLs...)."""
    found = Counter()
    for kind, pattern in _TOKEN_PATTERNS:
        for m in re.finditer(pattern, text):
            tok = re.sub(r"\s+", "", m.group(0)).rstrip(".,;:")
            if kind == "number":
                tok = tok.replace(",", "")
                if tok in {"", "-", "+"}:
                    continue
            found[(kind, tok)] += 1
    return found


def missing_tokens(original, rewritten):
    """Return the protected tokens present in `original` but lost in `rewritten`."""
    before = protected_tokens(original)
    after = protected_tokens(rewritten)
    after_values = Counter()
    for (kind, tok), n in after.items():
        after_values[tok] += n
    missing = []
    for (kind, tok), n in before.items():
        if after_values[tok] < 1:
            missing.append(f"{tok}")
    return sorted(set(missing))
