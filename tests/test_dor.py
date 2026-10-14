import json
from pathlib import Path

import pytest

from dor_fixture import write_dor_files
from taxappeal.connectors import Connectors, build_connectors, choices_from_env
from taxappeal.connectors.dor import DorPropertyRecords, DorSales, format_folio, import_dor
from taxappeal.models import CaseInput, PropertyUse, Recommendation, TrimNotice
from taxappeal.pipeline import generate_packet

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def dor_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dor")
    files = write_dor_files(tmp)
    db = tmp / "dor.sqlite"
    stats = import_dor(files["nal"], files["sdf"], db, files["coords"])
    assert stats["parcels"] == 76 and stats["sales"] == 74 and stats["parcels_with_coords"] == 76
    return db


@pytest.fixture(scope="module")
def dor_db_no_coords(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dor_nocoords")
    files = write_dor_files(tmp, with_coords=False)
    db = tmp / "dor.sqlite"
    import_dor(files["nal"], files["sdf"], db)
    return db


def dor_connectors(db):
    mock = build_connectors()
    return Connectors(DorPropertyRecords(db), DorSales(db), mock.trim_notices, mock.narrative)


def strong_case(**updates) -> CaseInput:
    case = CaseInput.model_validate(json.loads((EXAMPLES / "strong_case.json").read_text()))
    return case.model_copy(update=updates)


def test_property_record_from_roll(dor_db):
    prop = DorPropertyRecords(dor_db).get_property("3040190010100")
    assert prop.folio == "30-4019-001-0100"
    assert prop.building.use == PropertyUse.SINGLE_FAMILY
    assert prop.building.living_sqft == 1850 and prop.building.bedrooms is None
    assert prop.homestead and prop.exemptions_total == 50000
    assert prop.assessment_for(2026).just_value == 655000
    assert str(prop.last_sale_date) == "2025-03-15"
    assert prop.location.has_coords


def test_sales_filters_unqualified_nominal_and_vacant(dor_db):
    records, sales = DorPropertyRecords(dor_db), DorSales(dor_db)
    subject = records.get_property("30-4019-001-0100")
    from datetime import date
    found = sales.find_sales(subject, 2.0, date(2024, 7, 1), date(2025, 12, 31))
    assert found and all(s.price >= 10_000 for s in found)
    assert not any(s.price == 950000 and s.qualified for s in found)  # vacant-land sale
    qualified = [s for s in found if s.qualified]
    assert 0 < len(qualified) < len(found)  # code-11 sales present but not qualified


def test_packet_from_dor_data(dor_db):
    packet = generate_packet(strong_case(), dor_connectors(dor_db))
    assert packet.decision.recommendation == Recommendation.GO
    assert packet.valuation.requested_just_value < 655000
    assert all(c.distance_mi is not None for c in packet.valuation.comps)
    assert not any(a.factor in ("Bathrooms", "Pool") for c in packet.valuation.comps for a in c.adjustments)
    assert packet.data_sources["sales"] == "FL DOR Sale Data File (SDF)"


def test_neighborhood_fallback_without_coords(dor_db_no_coords):
    packet = generate_packet(strong_case(), dor_connectors(dor_db_no_coords))
    assert packet.valuation.comps and all(c.distance_mi is None for c in packet.valuation.comps)
    assert "same neighborhood" in packet.valuation.comps[0].selection_reason


def test_owner_confirmed_trim_and_cross_check(dor_db):
    trim = TrimNotice(folio="3040190010100", tax_year=2026, mailing_date="2026-08-24", just_value=660000,
                      assessed_value=655000, taxable_value=605000, prior_assessed_value=None,
                      total_millage=18.9)
    packet = generate_packet(strong_case(trim_notice=trim), dor_connectors(dor_db))
    assert any("just value ($660,000) differs" in w for w in packet.warnings)
    assert packet.data_sources["trim_notices"] == "owner-confirmed TRIM values"
    bad = trim.model_copy(update={"folio": "3099999990000"})
    with pytest.raises(ValueError, match="not 30-4019-001-0100"):
        generate_packet(strong_case(trim_notice=bad), dor_connectors(dor_db))


def test_import_rejects_missing_columns(tmp_path):
    (tmp_path / "nal.csv").write_text("CO_NO,PARCEL_ID\n23,1\n")
    (tmp_path / "sdf.csv").write_text("CO_NO\n23\n")
    with pytest.raises(ValueError, match="missing expected column"):
        import_dor(tmp_path / "nal.csv", tmp_path / "sdf.csv", tmp_path / "x.sqlite")


def test_unsupported_use_code(dor_db, tmp_path):
    import sqlite3, shutil
    db = tmp_path / "copy.sqlite"
    shutil.copy(dor_db, db)
    con = sqlite3.connect(db)
    con.execute("UPDATE parcels SET dor_uc = 3 WHERE folio = '3040190010100'")
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="use code 003"):
        DorPropertyRecords(db).get_property("3040190010100")


def test_folio_format_and_env_choices():
    assert format_folio("3040190010100") == "30-4019-001-0100"
    assert choices_from_env("property_records=dor, sales=dor") == {"property_records": "dor", "sales": "dor"}
    with pytest.raises(ValueError):
        choices_from_env("dor")


def test_dor_packet_renders(dor_db, dor_db_no_coords, tmp_path):
    from taxappeal.pipeline import write_outputs

    for db in (dor_db, dor_db_no_coords):
        packet = generate_packet(strong_case(), dor_connectors(db))
        files = write_outputs(packet, tmp_path / db.parent.name, pdf=False)
        html = files["evidence_html"].read_text()
        assert "Comparable Sales Grid" in html and "Bed / bath" not in html
        assert ("<svg" in html) == (db == dor_db)
