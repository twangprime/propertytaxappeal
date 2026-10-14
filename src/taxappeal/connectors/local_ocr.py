"""Read a TRIM notice without an API key: open-source OCR plus a rule-based parser.

1. Get the notice's text:
   * PDFs with a text layer (e.g. downloaded from the Property Appraiser's site): read directly
     with pypdf. No model needed.
   * Photos and scanned PDFs: GOT-OCR 2.0 (``stepfun-ai/GOT-OCR-2.0-hf``), an open-source page-OCR
     model from Hugging Face, run locally with ``transformers``. Override the model with
     TAXAPPEAL_OCR_MODEL. Weights (~1.5 GB) download on first use; a GPU is much faster but
     not required.
2. Parse the text with rules keyed on the notice's labels ("Market Value", "Assessed Value", ...).

The result has the same shape as the Claude reader's, and the owner reviews every value before
it is used. Anything the rules can't find is left blank for the owner to enter.

Install: ``pip install -e '.[local-ocr]'``
"""

from __future__ import annotations

import io
import os
import re
from datetime import date, datetime

from .ocr import OcrUnavailableError, TrimExtraction

DEFAULT_MODEL = os.environ.get("TAXAPPEAL_OCR_MODEL", "stepfun-ai/GOT-OCR-2.0-hf")
MIN_TEXT_LAYER_CHARS = 200

_MONEY = re.compile(r"\$?\b\d{1,3}(?:,\d{3})+\b|\$?\b\d{4,9}\b|(?<![\d.])\b0\b(?![.\d])")
_MILLS = re.compile(r"\b\d{1,2}\.\d{3,4}\b")
_DATE = re.compile(r"([A-Z][a-z]+\.? \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{4})")
_FOLIO = re.compile(r"\b(\d{2}-\d{4}-\d{3}-\d{4})\b|folio\s*(?:no\.?|number|#)?\s*[:#]?\s*([\d-]{13,17})", re.I)


def _parse_date(text: str) -> date | None:
    text = text.replace(".", "").replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _money_values(text: str) -> list[int]:
    return [int(m.replace("$", "").replace(",", "")) for m in _MONEY.findall(text)]


def _numbers_after(lines: list[str], i: int, label: re.Pattern, pattern: re.Pattern = _MONEY) -> list[str]:
    """Numbers on the label's line after the label, plus following lines that hold only numbers
    (text layers often put each table cell on its own line)."""
    found = pattern.findall(label.split(lines[i], maxsplit=1)[-1])
    for line in lines[i + 1:i + 6]:
        if re.search(r"[A-Za-z]", line):
            break
        found += pattern.findall(line)
    return found


def _labelled_values(lines: list[str], label: str, prefer: str | None = None,
                     avoid: str | None = None) -> tuple[int | None, int | None, str | None]:
    """(last year, this year, matched line) for a value row such as "Market Value 640,000 655,000"."""
    pattern = re.compile(label, re.I)
    candidates = [i for i, line in enumerate(lines) if pattern.search(line)]
    if prefer:
        preferred = [i for i in candidates if re.search(prefer, lines[i], re.I)]
        candidates = preferred or candidates
    if avoid:
        candidates = [i for i in candidates if not re.search(avoid, lines[i], re.I)] or candidates
    for i in candidates:
        values = [int(v.replace("$", "").replace(",", "")) for v in _numbers_after(lines, i, pattern)]
        values = [v for v in values if not 1900 <= v <= 2100]  # drop years in headers like "This Year (2026)"
        if values:
            return (values[0] if len(values) > 1 else None), values[-1], lines[i]
    return None, None, None


def parse_trim_text(text: str) -> TrimExtraction:
    """Rule-based extraction from the text of a TRIM notice."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    flat = " ".join(lines)
    notes: list[str] = []

    is_trim = bool(re.search(r"notice of proposed property taxes|truth in millage|\bTRIM\b", flat, re.I))
    folio_match = _FOLIO.search(flat)
    folio = (folio_match.group(1) or folio_match.group(2)) if folio_match else None

    year_match = re.search(r"tax year\D{0,10}(20\d\d)", flat, re.I) or re.search(r"this year\D{0,4}(20\d\d)", flat, re.I)
    tax_year = int(year_match.group(1)) if year_match else None

    mailing = re.search(r"mail(?:ing|ed)?(?: date)?\s*(?:on)?\s*[:\-]?\s*" + _DATE.pattern, flat, re.I)
    deadline = re.search(r"petition.{0,300}?(?:on or before|no later than|by)\s+" + _DATE.pattern, flat, re.I | re.S)

    _, just_value, _ = _labelled_values(lines, r"market value|just value")
    prior_assessed, assessed, assessed_line = _labelled_values(lines, r"assessed value", prefer=r"non-?\s?school",
                                                               avoid=r"(?<!non-)(?<!non )school")
    _, taxable, taxable_line = _labelled_values(lines, r"taxable value", prefer=r"non-?\s?school",
                                                avoid=r"(?<!non-)(?<!non )school")
    if assessed_line and "school" in assessed_line.lower() and "non" not in assessed_line.lower():
        notes.append("Only a school assessed value was found; check the non-school value.")

    total_millage = None
    for i, line in enumerate(lines):
        if re.match(r"total\b", line, re.I):
            mills = [float(m) for m in _numbers_after(lines, i, re.compile(r"total", re.I), _MILLS)]
            mills = [m for m in mills if 5 <= m <= 40]
            if mills:
                total_millage = mills[-1]
                notes.append("Total millage taken from the notice's Total row (proposed rate column).")
                break
    if total_millage is None:
        notes.append("Couldn't find a total millage. Add up this year's proposed rates for each taxing authority.")

    extraction = TrimExtraction(
        is_trim_notice=is_trim,
        folio=folio,
        property_address=None,
        tax_year=tax_year,
        mailing_date=_parse_date(mailing.group(1)) if mailing else None,
        petition_deadline=_parse_date(deadline.group(1)) if deadline else None,
        just_value=just_value,
        assessed_value=assessed,
        taxable_value=taxable,
        prior_assessed_value=prior_assessed,
        total_millage=total_millage,
        notes=notes,
    )
    if extraction.missing():
        extraction.notes.append(f"Not found on the notice: {', '.join(extraction.missing())}.")
    extraction.notes.append("Read automatically: compare every value with your notice.")
    return extraction


class GotOcrEngine:
    """Page OCR with GOT-OCR 2.0 via Hugging Face transformers. Loads the model on first use."""

    def __init__(self, model_id: str = DEFAULT_MODEL, device: str | None = None):
        self.model_id = model_id
        self.device = device
        self._model = self._processor = None

    def _load(self) -> None:
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as e:
            raise OcrUnavailableError(
                "Reading photos and scanned PDFs needs the local OCR model: pip install -e '.[local-ocr]'"
            ) from e
        if self.device is None:
            self.device = "cuda" if torch.cuda.is_available() else (
                "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForImageTextToText.from_pretrained(self.model_id, dtype=dtype).to(self.device)
        self._model.eval()

    def image_to_text(self, image) -> str:
        if self._model is None:
            self._load()
        # crop_to_patches tiles the page so small print on a full-page notice stays legible.
        inputs = self._processor(image, return_tensors="pt", crop_to_patches=True, max_patches=6).to(self.device)
        output = self._model.generate(**inputs, do_sample=False, tokenizer=self._processor.tokenizer,
                                      stop_strings="<|im_end|>", max_new_tokens=4096)
        return self._processor.decode(output[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)


class LocalTrimReader:
    """Same interface as ClaudeTrimReader: ``extract(data, media_type) -> TrimExtraction``."""

    label = "local open-source OCR"

    def __init__(self, engine: GotOcrEngine | None = None):
        self.engine = engine or GotOcrEngine()

    def text_of(self, data: bytes, media_type: str) -> tuple[str, str]:
        """(text, how it was obtained)."""
        if media_type == "application/pdf":
            text = _pdf_text_layer(data)
            if len(text.strip()) >= MIN_TEXT_LAYER_CHARS:
                return text, "PDF text layer"
            images = _pdf_to_images(data)
        else:
            images = [_open_image(data)]
        return "\n".join(self.engine.image_to_text(img) for img in images), f"OCR ({self.engine.model_id})"

    def extract(self, data: bytes, media_type: str) -> TrimExtraction:
        text, source = self.text_of(data, media_type)
        extraction = parse_trim_text(text)
        extraction.notes.insert(0, f"Text source: {source}.")
        return extraction

    def extract_file(self, path) -> TrimExtraction:
        from .ocr import media_type_for

        return self.extract(path.read_bytes(), media_type_for(path.name))


def _pdf_text_layer(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise OcrUnavailableError("Reading PDFs needs pypdf: pip install -e '.[local-ocr]'") from e
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages[:4])


def _pdf_to_images(data: bytes, max_pages: int = 2):
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise OcrUnavailableError("Reading scanned PDFs needs pypdfium2: pip install -e '.[local-ocr]'") from e
    pdf = pdfium.PdfDocument(data)
    return [pdf[i].render(scale=2).to_pil().convert("RGB") for i in range(min(len(pdf), max_pages))]


def _open_image(data: bytes):
    try:
        from PIL import Image, ImageOps
    except ImportError as e:
        raise OcrUnavailableError("Reading photos needs Pillow: pip install -e '.[local-ocr]'") from e
    return ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
