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
