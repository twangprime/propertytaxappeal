import io
from datetime import date
from pathlib import Path

import pytest

from taxappeal.connectors.local_ocr import LocalTrimReader, parse_trim_text
from taxappeal.connectors.ocr import OcrUnavailableError

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_trim_notice.pdf"

# Roughly what a page-OCR model returns for a photographed notice: table rows stay on one line.
OCR_TEXT = """NOTICE OF PROPOSED PROPERTY TAXES  DO NOT PAY
MIAMI-DADE COUNTY
FOLIO NUMBER: 30-5911-003-0780   TAX YEAR 2026
Mailed August 22, 2026
Taxing Authority       Last Year   Rolled-back   Proposed
School Board           5.6000      5.3816        5.5480
County                 4.5740      4.4368        4.5740
TOTAL                  18.1010     17.4012       18.0420
                       Last Year (2025)   This Year (2026)
Market Value           $600,000           $640,000
Assessed Value (School)        300,000      330,000
Assessed Value (Non-School)    300,000      330,000
Taxable Value (School)         275,000      305,000
Taxable Value (Non-School)     250,000      280,000
A petition must be filed with the Value Adjustment Board no later than September 16, 2026.
"""


class FakeEngine:
    model_id = "fake/ocr"

    def __init__(self, text=OCR_TEXT):
        self.text, self.calls = text, 0

    def image_to_text(self, image):
        self.calls += 1
        return self.text


def test_text_layer_pdf_needs_no_model():
    engine = FakeEngine()
    e = LocalTrimReader(engine).extract(SAMPLE.read_bytes(), "application/pdf")
    assert engine.calls == 0
    assert (e.folio, e.tax_year, e.just_value, e.assessed_value, e.taxable_value, e.prior_assessed_value) == \
        ("30-4019-001-0100", 2026, 655000, 655000, 605000, 610000)
    assert e.total_millage == 15.9288
    assert e.mailing_date == date(2026, 8, 24) and e.petition_deadline == date(2026, 9, 18)
    assert e.notes[0] == "Text source: PDF text layer." and not e.missing()
    assert e.to_trim_notice().just_value == 655000


def test_ocr_style_text_prefers_non_school_values():
    e = parse_trim_text(OCR_TEXT)
    assert e.is_trim_notice and e.folio == "30-5911-003-0780" and e.tax_year == 2026
    assert (e.just_value, e.assessed_value, e.prior_assessed_value, e.taxable_value) == (640000, 330000, 300000, 280000)
    assert e.total_millage == 18.042
    assert e.mailing_date == date(2026, 8, 22) and e.petition_deadline == date(2026, 9, 16)


def test_photo_goes_through_ocr_model():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    engine = FakeEngine()
    e = LocalTrimReader(engine).extract(buf.getvalue(), "image/png")
    assert engine.calls == 1 and e.notes[0] == "Text source: OCR (fake/ocr)."
    assert e.taxable_value == 280000


def test_scanned_pdf_is_rasterized_and_ocred():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 260), "white").save(buf, format="PDF")
    engine = FakeEngine()
    LocalTrimReader(engine).extract(buf.getvalue(), "application/pdf")
    assert engine.calls == 1


def test_missing_millage_left_for_owner():
    e = parse_trim_text(OCR_TEXT.replace("TOTAL                  18.1010     17.4012       18.0420\n", ""))
    assert e.total_millage is None and "total_millage" in e.missing()
    assert any("Add up this year's proposed rates" in n for n in e.notes)
    with pytest.raises(ValueError):
        e.to_trim_notice()


def test_non_trim_document():
    assert not parse_trim_text("Electric bill\nAmount due $142.17\n").is_trim_notice


def test_model_missing_gives_install_hint(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name in ("torch", "transformers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    from taxappeal.connectors.local_ocr import GotOcrEngine

    with pytest.raises(OcrUnavailableError, match="local-ocr"):
        GotOcrEngine().image_to_text(None)


MIAMI_DADE_SAMPLE = SAMPLE.with_name("sample_trim_notice_miami_dade.pdf")


def test_miami_dade_layout_pdf():
    """Real notices store the form and the values as separate text; rows must be rebuilt by position."""
    e = LocalTrimReader(FakeEngine()).extract(MIAMI_DADE_SAMPLE.read_bytes(), "application/pdf")
    assert e.folio == "30-4019-001-0100" and e.tax_year == 2026
    assert (e.just_value, e.assessed_value, e.prior_assessed_value) == (705000, 655000, 610000)
    assert e.taxable_value == 605000  # non-school "Current Taxable Value" (Countywide row), not the school row
    assert e.total_millage == 14.8962  # sum of the proposed-budget rates
    assert e.petition_deadline == date(2026, 9, 18)
    assert not e.missing()


def test_miami_dade_rows_from_ocr_text():
    text = """NOTICE OF PROPOSED PROPERTY TAXES AND
FOLIO: 30-0000-000-0001
MIAMI-DADE COUNTY:
Countywide 500,000 4.5740 2,287.00 510,000 4.3301 2,208.35 4.5740 2,332.74
PUBLIC SCHOOLS:
By State Law 525,000 3.2510 1,706.78 535,000 3.1210 1,669.74 3.2510 1,739.29
PRIOR VALUE ( 20 2 5 ) 700,000 550,000 550,000
CURRENT VALUE (2026) 720,000 560,000 560,000
Petitions must be filed on or before
SEPT. 16, 2026"""
    e = parse_trim_text(text)
    assert (e.just_value, e.assessed_value, e.prior_assessed_value, e.taxable_value) == (720000, 560000, 550000, 510000)
    assert e.total_millage == 7.825 and e.tax_year == 2026 and e.petition_deadline == date(2026, 9, 16)
