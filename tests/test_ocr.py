import json
from datetime import date
from types import SimpleNamespace

import pytest

from taxappeal.connectors.ocr import TRIM_SCHEMA, ClaudeTrimReader, OcrTrimNotices, media_type_for
from taxappeal.models import CaseInput

GOOD = {
    "is_trim_notice": True, "folio": "30-4019-001-0100", "property_address": "1200 Mockingbird St",
    "tax_year": 2026, "mailing_date": "2026-08-24", "petition_deadline": "2026-09-18",
    "just_value": 655000, "assessed_value": 655000, "taxable_value": 605000,
    "prior_assessed_value": 610000, "total_millage": 18.9, "notes": ["Summed 9 authorities."],
}


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.calls = payload, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


def reader(payload, stop_reason="end_turn"):
    messages = FakeMessages(payload, stop_reason)
    return ClaudeTrimReader(client=SimpleNamespace(beta=SimpleNamespace(messages=messages))), messages


def test_extracts_pdf_with_structured_output():
    r, messages = reader(GOOD)
    extraction = r.extract(b"%PDF-1.4 fake", "application/pdf")
    trim = extraction.to_trim_notice()
    assert trim.just_value == 655000 and trim.petition_deadline == date(2026, 9, 18)
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": TRIM_SCHEMA}
    assert call["messages"][0]["content"][0]["type"] == "document"


def test_image_uses_image_block():
    r, messages = reader(GOOD)
    r.extract(b"\x89PNG fake", "image/png")
    assert messages.calls[0]["messages"][0]["content"][0]["type"] == "image"


def test_missing_values_require_manual_entry():
    r, _ = reader({**GOOD, "just_value": None, "notes": ["Market value smudged."]})
    extraction = r.extract(b"x", "image/jpeg")
    assert extraction.missing() == ["just_value"]
    with pytest.raises(ValueError, match="just_value"):
        extraction.to_trim_notice()


def test_not_a_trim_notice():
    r, _ = reader({**GOOD, "is_trim_notice": False})
    with pytest.raises(ValueError, match="does not look like a TRIM notice"):
        r.extract(b"x", "image/jpeg").to_trim_notice()


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reasons(stop):
    r, _ = reader(GOOD, stop_reason=stop)
    with pytest.raises(ValueError):
        r.extract(b"x", "application/pdf")


def test_unparseable_output():
    r, _ = reader("not json")
    with pytest.raises(ValueError, match="Could not parse"):
        r.extract(b"x", "application/pdf")


def test_media_types():
    assert media_type_for("notice.PDF") == "application/pdf"
    assert media_type_for("photo.jpg") == "image/jpeg"
    assert media_type_for("upload", "image/png; charset=binary") == "image/png"
    with pytest.raises(ValueError):
        media_type_for("notice.docx")


def test_trim_source_reads_case_file(tmp_path):
    f = tmp_path / "notice.pdf"
    f.write_bytes(b"%PDF fake")
    r, _ = reader(GOOD)
    case = CaseInput(folio="30-4019-001-0100", tax_year=2026, trim_notice_path=str(f),
                     owner={"name": "A", "mailing_address": "B"})
    assert OcrTrimNotices(r).get_trim_notice(case).taxable_value == 605000
    with pytest.raises(ValueError, match="No TRIM notice file"):
        OcrTrimNotices(r).get_trim_notice(case.model_copy(update={"trim_notice_path": None}))
