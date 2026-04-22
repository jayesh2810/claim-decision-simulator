"""Extract text from uploaded claim documents: PDFs (text + OCR fallback) and raster images."""

from __future__ import annotations

import io
import json
import shutil
import uuid
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

# Minimum characters per page to treat as having a text layer
_MIN_PAGE_TEXT_CHARS = 40


def tesseract_available() -> tuple[bool, str | None]:
    """Return (ok, error_message_if_not). Lazy-import pytesseract so the API can boot without it."""
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except ModuleNotFoundError:
        return (
            False,
            "Python package pytesseract is not installed. Run: pip install pytesseract "
            "(or pip install -r requirements.txt from the project root).",
        )
    try:
        pytesseract.get_tesseract_version()
        return True, None
    except TesseractNotFoundError as e:
        return False, str(e)
    except Exception as e:  # pragma: no cover
        return False, str(e)


def _ocr_pil(img: Image.Image) -> str:
    try:
        from pytesseract import TesseractNotFoundError, image_to_string
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "pytesseract is not installed. Run: pip install pytesseract "
            "(or pip install -r requirements.txt from the project root)."
        ) from e
    try:
        return image_to_string(img.convert("RGB"), lang="eng")
    except TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract OCR binary is not installed or not on PATH. "
            "Install it: macOS `brew install tesseract`, Ubuntu `apt install tesseract-ocr`."
        ) from None


def extract_from_image_path(path: Path) -> str:
    with Image.open(path) as img:
        return _ocr_pil(img)


def extract_from_pdf_path(path: Path) -> str:
    doc = fitz.open(path)
    parts: list[str] = []
    try:
        for i in range(len(doc)):
            page = doc.load_page(i)
            text = (page.get_text() or "").strip()
            if len(text) >= _MIN_PAGE_TEXT_CHARS:
                parts.append(f"--- Page {i + 1} ---\n{text}")
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            mode = "RGB" if pix.n == 3 else "RGBA"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            if mode == "RGBA":
                img = img.convert("RGB")
            try:
                ocr_text = _ocr_pil(img).strip()
            except RuntimeError as e:
                # Allow uploads to proceed for mostly-readable PDFs without a full OCR stack.
                fallback = text.strip()
                note = f"[OCR unavailable for this page — install `pytesseract`, the Tesseract binary (e.g. brew install tesseract), and try again. {e}]"
                block = f"{fallback}\n\n{note}" if fallback else note
                parts.append(f"--- Page {i + 1} ---\n{block}")
                continue
            combined = text + ("\n" + ocr_text if ocr_text else "")
            parts.append(f"--- Page {i + 1} ---\n{combined or '[no text extracted]'}")
    finally:
        doc.close()
    return "\n\n".join(parts)


_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".json"}


def allowed_suffix(path: Path) -> bool:
    return path.suffix.lower() in _ALLOWED


def save_upload_bytes(upload_dir: Path, data: bytes, original_name: str) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower() or ".bin"
    if suffix not in _ALLOWED:
        raise ValueError(f"Unsupported file extension: {suffix}")
    if len(data) == 0:
        raise ValueError("Empty file")
    dest = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    return dest


def save_upload_to_disk(
    upload_dir: Path,
    source_fileobj: io.BufferedReader,
    original_name: str,
) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower() or ".bin"
    if suffix not in _ALLOWED:
        raise ValueError(f"Unsupported file extension: {suffix}")
    dest = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(source_fileobj, out)
    return dest


def extract_from_json_path(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    try:
        obj = json.loads(raw)
        return json.dumps(obj, indent=2)
    except json.JSONDecodeError:
        return raw


def extract_document_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        return extract_from_pdf_path(path)
    if suf in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        return extract_from_image_path(path)
    if suf == ".json":
        return extract_from_json_path(path)
    raise ValueError(f"Unsupported file type: {suf}")
