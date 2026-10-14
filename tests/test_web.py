import json

import pytest

from taxappeal.web import App, case_from_form


def form(**overrides):
    base = {
        "folio": ["30-4019-001-0100"], "tax_year": ["2026"], "owner_name": ["Jordan Sample"],
        "mailing_address": ["1200 Mockingbird St"], "phone": [""], "email": [""],
        "hearing_date": ["2026-11-18"], "petition_filed": ["on"],
        "repair_description": ["Roof", ""], "repair_amount": ["$28,000", ""], "repair_source": ["", ""],
    }
    base.update(overrides)
    return base


def test_case_from_form_parses_repairs_and_flags():
    case = case_from_form(form())
    assert case.petition_filed and not case.recent_improvements
    assert [(r.description, r.amount, r.source) for r in case.repair_estimates] == [("Roof", 28000, "owner estimate")]
    assert str(case.hearing_date) == "2026-11-18"


def test_bad_hearing_date_rejected():
    with pytest.raises(ValueError):
        case_from_form(form(hearing_date=["garbage"]))


def test_generate_and_render_result(tmp_path):
    app = App(tmp_path)
    run_id = app.generate(form(), pdf=False)
    page = app.result_page(run_id)
    assert "Yes, appeal" in page and "evidence.html" in page
    assert json.loads((tmp_path / run_id / "meta.json").read_text()) == {"pdf": False}
    assert app.result_page("../etc") is None
    assert app.result_page("does-not-exist") is None


def test_form_page_lists_mock_folios(tmp_path):
    page = App(tmp_path).form_page(error="oops")
    assert "30-5911-003-0780" in page and "oops" in page


def test_manual_trim_values_become_owner_confirmed_notice():
    case = case_from_form(form(trim_just_value=["$660,000"], trim_assessed_value=["655,000"],
                               trim_taxable_value=["605000"], trim_total_millage=["18.9"],
                               trim_prior_assessed_value=[""], trim_petition_deadline=["2026-09-18"]))
    assert case.trim_notice.just_value == 660000 and case.trim_notice.prior_assessed_value is None
    assert str(case.trim_notice.petition_deadline) == "2026-09-18"


def test_partial_trim_values_rejected():
    with pytest.raises(ValueError, match="assessed value"):
        case_from_form(form(trim_just_value=["660000"]))


def test_multipart_parsing():
    from taxappeal.web import parse_body

    boundary = "XyZ"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"folio\"\r\n\r\n30-4019-001-0100\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"trim_file\"; filename=\"n.pdf\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n%PDF-1.4 data\r\n--{boundary}--\r\n"
    ).encode()
    fields, files = parse_body(f"multipart/form-data; boundary={boundary}", body)
    assert fields["folio"] == ["30-4019-001-0100"]
    assert files["trim_file"] == ("n.pdf", "application/pdf", b"%PDF-1.4 data")


def test_extract_prefills_form_for_confirmation(tmp_path):
    from test_ocr import GOOD, reader

    r, _ = reader(GOOD)
    app = App(tmp_path, trim_reader=r)
    page = app.extract_trim(form(), {"trim_file": ("n.pdf", "application/pdf", b"%PDF")})
    assert 'value="655000"' in page and "Check each one" in page and "Summed 9 authorities." in page
    assert 'name="trim_folio" value="30-4019-001-0100"' in page


def test_extract_failure_falls_back_to_manual_entry(tmp_path):
    class Broken:
        def extract(self, data, media_type):
            raise RuntimeError("no API key")

    page = App(tmp_path, trim_reader=Broken()).extract_trim(form(), {"trim_file": ("n.pdf", "application/pdf", b"x")})
    assert "type the values" in page and "no API key" in page


def test_generate_with_confirmed_trim_for_wrong_property_is_rejected(tmp_path):
    bad = form(trim_folio=["30-9999-999-9999"], trim_just_value=["1"], trim_assessed_value=["1"],
               trim_taxable_value=["1"], trim_total_millage=["18"])
    with pytest.raises(ValueError, match="TRIM notice is for folio"):
        App(tmp_path).generate(bad, pdf=False)


def test_serve_explains_missing_dor_index(tmp_path, monkeypatch):
    from taxappeal.web import serve

    monkeypatch.setenv("TAXAPPEAL_CONNECTORS", "property_records=dor,sales=dor")
    monkeypatch.setenv("TAXAPPEAL_DOR_DB", str(tmp_path / "missing.sqlite"))
    monkeypatch.setattr("taxappeal.connectors.dor.DEFAULT_DB", tmp_path / "missing.sqlite")
    with pytest.raises(SystemExit, match="import-dor"):
        serve(port=0, out_root=tmp_path / "web")


def test_read_my_notice_works_without_api_key(tmp_path):
    from pathlib import Path

    pdf = (Path(__file__).resolve().parents[1] / "samples" / "sample_trim_notice.pdf").read_bytes()
    page = App(tmp_path).extract_trim(form(folio=[""]), {"trim_file": ("notice.pdf", "application/pdf", pdf)})
    assert 'value="655000"' in page and 'value="15.9288"' in page and 'value="2026-09-18"' in page
    assert 'name="folio" type="text"' in page and 'value="30-4019-001-0100"' in page
    assert "Text source: PDF text layer." in page
