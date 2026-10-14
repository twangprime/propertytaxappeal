"""Read values from a homeowner's TRIM notice ("Notice of Proposed Property Taxes") with Claude.

Accepts a PDF or a photo. The model returns JSON constrained to ``TRIM_SCHEMA``; we validate it,
and the owner confirms the values before they are used (the web UI shows them for review).

Needs the ``anthropic`` package (``pip install -e '.[ocr]'``) and credentials
(``ANTHROPIC_API_KEY``, or an ``ant auth login`` profile).
"""

from __future__ import annotations

import base64
import json
import mimetypes
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ..models import CaseInput, TrimNotice

MODEL = "claude-opus-5-5"
MAX_BYTES = 20 * 1024 * 1024
MEDIA_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}

def _nullable(schema: dict, description: str = "") -> dict:
    out = {"anyOf": [schema, {"type": "null"}]}
    return {**out, "description": description} if description else out


_NULLABLE_INT = _nullable({"type": "integer"})
_NULLABLE_DATE = _nullable({"type": "string", "format": "date"})
TRIM_SCHEMA = {
    "type": "object",
    "properties": {
        "is_trim_notice": {"type": "boolean"},
        "folio": _nullable({"type": "string"}, "Folio / parcel ID exactly as printed"),
        "property_address": _nullable({"type": "string"}),
        "tax_year": _NULLABLE_INT,
        "mailing_date": _NULLABLE_DATE,
        "petition_deadline": _NULLABLE_DATE,
        "just_value": _NULLABLE_INT,
        "assessed_value": _NULLABLE_INT,
        "taxable_value": _NULLABLE_INT,
        "prior_assessed_value": _NULLABLE_INT,
        "total_millage": _nullable({"type": "number"}),
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["is_trim_notice", "folio", "property_address", "tax_year", "mailing_date",
                 "petition_deadline", "just_value", "assessed_value", "taxable_value",
                 "prior_assessed_value", "total_millage", "notes"],
    "additionalProperties": False,
}

PROMPT = """This should be a Florida "Notice of Proposed Property Taxes" (TRIM notice) from Miami-Dade County.
Extract the values below exactly as printed. Do not estimate or compute anything except the millage total.
Use null for anything you cannot read with confidence, and say why in notes.

- folio: the folio / parcel number.
- tax_year: the tax year of the proposed taxes (this year, not last year).
- mailing_date: the date the notice was mailed, if printed.
- petition_deadline: the last date to file a petition with the Value Adjustment Board, if printed.
- just_value: this year's market (just) value.
- assessed_value: this year's assessed value. If school and non-school assessed values differ, use the
  non-school value and mention both in notes.
- taxable_value: this year's taxable value for non-school levies (same rule as above).
- prior_assessed_value: LAST year's assessed value (the prior-year column), same school/non-school rule.
- total_millage: the sum of this year's PROPOSED millage rates across all taxing authorities (the column
  for taxes if the proposed budget is adopted), in mills. Report the authorities you summed in notes.
- notes: anything unreadable, ambiguous, or unusual. Set is_trim_notice false if this is not a TRIM notice."""


class TrimExtraction(BaseModel):
    is_trim_notice: bool
    folio: str | None
    property_address: str | None
    tax_year: int | None
    mailing_date: date | None
    petition_deadline: date | None
    just_value: int | None
    assessed_value: int | None
    taxable_value: int | None
    prior_assessed_value: int | None
    total_millage: float | None
    notes: list[str]

    def missing(self) -> list[str]:
        required = ["folio", "tax_year", "just_value", "assessed_value", "taxable_value", "total_millage"]
        return [f for f in required if getattr(self, f) is None]

    def to_trim_notice(self, fallback_mailing_date: date | None = None) -> TrimNotice:
        if not self.is_trim_notice:
            raise ValueError("The uploaded document does not look like a TRIM notice.")
        missing = self.missing()
        if missing or not (self.mailing_date or fallback_mailing_date):
            raise ValueError(f"Could not read: {', '.join(missing or ['mailing date'])}. Enter them manually.")
        return TrimNotice(
            folio=self.folio, tax_year=self.tax_year,
            mailing_date=self.mailing_date or fallback_mailing_date,
            just_value=self.just_value, assessed_value=self.assessed_value,
            taxable_value=self.taxable_value, prior_assessed_value=self.prior_assessed_value,
            total_millage=self.total_millage, petition_deadline=self.petition_deadline,
        )


class OcrUnavailableError(RuntimeError):
    pass


def media_type_for(filename: str, declared: str | None = None) -> str:
    media = (declared or "").split(";")[0].strip().lower()
    if media not in MEDIA_TYPES:
        media = mimetypes.guess_type(filename)[0] or ""
    if media == "image/jpg":
        media = "image/jpeg"
    if media not in MEDIA_TYPES:
        raise ValueError(f"Unsupported file type for {filename!r}. Upload a PDF, JPEG, PNG, GIF or WebP.")
    return media


class ClaudeTrimReader:
    def __init__(self, client=None, model: str = MODEL):
        if client is None:
            try:
                import anthropic
            except ImportError as e:
                raise OcrUnavailableError("OCR needs the anthropic package: pip install -e '.[ocr]'") from e
            client = anthropic.Anthropic()
        self.client = client
        self.model = model

    def extract(self, data: bytes, media_type: str) -> TrimExtraction:
        if len(data) > MAX_BYTES:
            raise ValueError("File is larger than 20 MB.")
        source = {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()}
        block = {"type": "document" if media_type == "application/pdf" else "image", "source": source}
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": TRIM_SCHEMA}},
            messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
        )
        if response.stop_reason == "refusal":
            raise ValueError("The document could not be processed. Enter the TRIM values manually.")
        if response.stop_reason == "max_tokens":
            raise ValueError("The extraction was cut off. Try again or enter the values manually.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return TrimExtraction.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Could not parse the extracted values: {e}") from e

    def extract_file(self, path: Path) -> TrimExtraction:
        return self.extract(path.read_bytes(), media_type_for(path.name))


class OcrTrimNotices:
    """TrimNoticeSource that reads ``case.trim_notice_path`` with Claude."""

    name = "OCR of the owner's TRIM notice (Claude)"

    def __init__(self, reader: ClaudeTrimReader | None = None):
        self._reader = reader

    @property
    def reader(self) -> ClaudeTrimReader:
        if self._reader is None:
            self._reader = ClaudeTrimReader()
        return self._reader

    def get_trim_notice(self, case: CaseInput) -> TrimNotice:
        if not case.trim_notice_path:
            raise ValueError("No TRIM notice file was provided. Upload it or enter the values manually.")
        return self.reader.extract_file(Path(case.trim_notice_path)).to_trim_notice()
