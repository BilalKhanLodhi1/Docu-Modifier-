"""DOCX <-> PDF conversion with honest diagnostics.

DOCX -> PDF uses LibreOffice headless (invoked with an argument list, never a
shell string). PDF -> DOCX uses pdf2docx for digital PDFs and Tesseract OCR
for scanned ones.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from .document_reader import inspect_pdf
from .exceptions import DependencyMissingError, DocuCraftError

log = logging.getLogger("docucraft.convert")

MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def find_soffice():
    candidates = [getattr(settings, "LIBREOFFICE_PATH", ""), shutil.which("soffice"),
                  shutil.which("libreoffice"), MAC_SOFFICE]
    for c in candidates:
        if c and Path(c).exists() and os.access(c, os.X_OK):
            return c
    return None


def find_tesseract():
    path = getattr(settings, "TESSERACT_PATH", "") or shutil.which("tesseract")
    return path if path and Path(path).exists() else None


def dependency_status():
    status = {}
    so = find_soffice()
    status["libreoffice"] = (bool(so), so or "Not found. Install LibreOffice to enable Word to PDF conversion.")
    try:
        import pdf2docx  # noqa: F401
        status["pdf2docx"] = (True, "Installed")
    except ImportError:
        status["pdf2docx"] = (False, "pip install pdf2docx")
    tess = find_tesseract()
    status["tesseract"] = (bool(tess), tess or "Not found. Install Tesseract to enable OCR for scanned PDFs (optional).")
    try:
        import rembg  # noqa: F401
        status["rembg"] = (True, "Installed")
    except ImportError:
        status["rembg"] = (False, "Optional: pip install rembg for background removal.")
    return status


def docx_to_pdf(src_path, dst_path, timeout=None):
    soffice = find_soffice()
    if not soffice:
        raise DependencyMissingError(
            "Word to PDF conversion needs LibreOffice. On macOS run: brew install --cask libreoffice, "
            "or set LIBREOFFICE_PATH in .env.")
    timeout = timeout or settings.DOCUCRAFT_JOB_TIMEOUT
    with tempfile.TemporaryDirectory(prefix="dc_lo_") as tmp:
        tmp = Path(tmp)
        src_copy = tmp / "input.docx"
        shutil.copyfile(src_path, src_copy)
        profile = (tmp / "profile").as_uri()
        cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
               "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(tmp), str(src_copy)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise DocuCraftError("The conversion took too long and was stopped. Try a smaller document.")
        out = tmp / "input.pdf"
        if proc.returncode != 0 or not out.exists():
            log.warning("LibreOffice failed rc=%s stderr=%s", proc.returncode, proc.stderr[:500])
            raise DocuCraftError("LibreOffice could not convert this document. It may use unsupported features.")
        shutil.move(str(out), dst_path)
    return dst_path


def pdf_warnings(info):
    w = []
    if info.get("needs_ocr"):
        w.append("This PDF looks scanned or image-only. Text can only be recovered with OCR, and layout will be simplified.")
    if info.get("multi_column_pages"):
        w.append(f"{info['multi_column_pages']} page(s) use a multi-column layout, which may convert into text boxes or reordered paragraphs.")
    if info.get("images", 0) > info.get("page_count", 1) * 3:
        w.append("The PDF contains many images; some may be repositioned in Word.")
    if info.get("font_count", 0) > 12:
        w.append("Many embedded fonts were found. Fonts missing on your computer will be substituted.")
    w.append("Complex tables, charts, diagrams and handwritten content may not convert exactly. Review the result before use.")
    return w


def pdf_to_docx(src_path, dst_path, ocr="auto", ocr_lang="eng", progress=None):
    """Convert a PDF to DOCX. ocr: 'auto' | 'force' | 'off'. Returns a summary dict."""
    progress = progress or (lambda *a, **k: None)
    info = inspect_pdf(src_path)
    use_ocr = ocr == "force" or (ocr == "auto" and info["needs_ocr"])
    if info["needs_ocr"] and ocr == "off":
        raise DocuCraftError("This PDF has no extractable text (it looks scanned). Enable OCR to convert it.")
    if use_ocr:
        pages = _ocr_pdf_to_docx(src_path, dst_path, ocr_lang, progress)
        method = "OCR (Tesseract)"
    else:
        try:
            from pdf2docx import Converter
        except ImportError:
            raise DependencyMissingError("PDF to Word conversion needs pdf2docx: pip install pdf2docx")
        progress("converting", 30, "Reconstructing paragraphs, tables and images")
        cv = Converter(str(src_path))
        try:
            cv.convert(str(dst_path), start=0, end=None)
        except Exception as exc:
            log.warning("pdf2docx failed: %s", exc)
            raise DocuCraftError("The PDF structure could not be reconstructed. Try OCR mode instead.")
        finally:
            cv.close()
        pages = info["page_count"]
        method = "Layout reconstruction (pdf2docx)"
    return {"pages": pages, "method": method, "warnings": pdf_warnings(info), "ocr": use_ocr}


def _ocr_pdf_to_docx(src_path, dst_path, lang, progress):
    tess = find_tesseract()
    if not tess:
        raise DependencyMissingError("OCR needs Tesseract. On macOS run: brew install tesseract")
    import docx
    import pymupdf
    import pytesseract
    from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = tess
    out = docx.Document()
    with pymupdf.open(str(src_path)) as pdf:
        n = pdf.page_count
        for i, page in enumerate(pdf):
            progress("converting", 20 + int(70 * i / max(1, n)), f"Reading text on page {i + 1} of {n}")
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            try:
                text = pytesseract.image_to_string(img, lang=lang)
            except pytesseract.TesseractError as exc:
                raise DocuCraftError(f"OCR failed. Check that the '{lang}' language pack is installed.") from exc
            blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
            for b in blocks:
                out.add_paragraph(" ".join(line.strip() for line in b.splitlines()))
            if i < n - 1:
                out.add_page_break()
    out.save(str(dst_path))
    return n
