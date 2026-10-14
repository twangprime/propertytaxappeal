import json
from datetime import date
from pathlib import Path

import pytest

from taxappeal.connectors import Connectors, build_connectors
from taxappeal.connectors.mock import MockSales
from taxappeal.deadlines import build_deadlines, to_ics
from taxappeal.models import CaseInput, Recommendation
from taxappeal.narrative import check_numbers_grounded
from taxappeal.pipeline import generate_packet, write_outputs
from taxappeal.rules import rules_for

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_case(name: str) -> CaseInput:
    return CaseInput.model_validate(json.loads((EXAMPLES / name).read_text()))


@pytest.fixture
def connectors() -> Connectors:
    return build_connectors()


def test_strong_case_recommends_appeal(connectors):
    packet = generate_packet(load_case("strong_case.json"), connectors)
    v, d = packet.valuation, packet.decision
    assert d.recommendation == Recommendation.GO
    assert v.repair_deduction == 37500
    assert v.requested_just_value < v.current_just_value
    assert v.requested_just_value == round((v.indicated_market_value - 37500) * 0.85, -3)
    assert 3 <= len(v.comps) <= 5
    assert all(c.sale.qualified and c.sale.building.use == packet.property.building.use for c in v.comps)
    assert abs(sum(c.weight for c in v.comps) - 1) < 0.01
    assert d.estimated_annual_savings > 0


def test_fairly_assessed_condo_is_no_go(connectors):
    packet = generate_packet(load_case("fair_condo.json"), connectors)
    assert packet.decision.recommendation == Recommendation.NO_GO
    assert packet.decision.estimated_annual_savings == 0
    assert any(a.code == "value_supported" for a in packet.valuation.audits)


def test_cap_error_detected(connectors):
    packet = generate_packet(load_case("cap_error.json"), connectors)
    cap = next(a for a in packet.valuation.audits if a.code == "cap_exceeded")
    assert cap.amount == 330000 - 309000
    assert packet.decision.recommendation == Recommendation.GO
    assert packet.decision.new_assessed_value <= 309000
    assert "assessment cap" in packet.petition_fields["Reason(s) for petition"]


def test_soh_protected_overvaluation_saves_nothing(connectors):
    packet = generate_packet(load_case("soh_protected.json"), connectors)
    assert packet.decision.just_value_reduction > 0
    assert packet.decision.estimated_annual_savings == 0
    assert packet.decision.recommendation == Recommendation.NO_GO
    assert any("portability" in r for r in packet.decision.reasons)


def test_cap_reset_after_sale_is_not_flagged(connectors):
    packet = generate_packet(load_case("strong_case.json"), connectors)
    codes = {a.code for a in packet.valuation.audits}
    assert "cap_reset" in codes and "cap_exceeded" not in codes


def test_narrative_grounding_rejects_invented_figures(connectors):
    packet = generate_packet(load_case("strong_case.json"), connectors)
    assert check_numbers_grounded(packet.narrative, packet.valuation, packet.decision) == []
    tampered = packet.narrative.model_copy(update={"summary": "The home is worth $123,456."})
    assert check_numbers_grounded(tampered, packet.valuation, packet.decision) == ["$123,456"]


def test_deadlines_relative_to_hearing():
    case = load_case("strong_case.json")
    trim = build_connectors().trim_notices.get_trim_notice(case.folio, 2026)
    deadlines = {d.name: d for d in build_deadlines(case, trim, rules_for(2026))}
    assert deadlines["Send your evidence to the Property Appraiser"].due == date(2026, 11, 3)
    assert deadlines["Pay at least 75% of taxes"].due == date(2027, 3, 31)
    assert not deadlines["Upload evidence to the VAB portal"].verified
    # Already filed: the past petition deadline is omitted.
    assert "File petition (DR-486) with the VAB" not in deadlines

    unfiled = case.model_copy(update={"petition_filed": False, "hearing_date": None})
    names = [d.name for d in build_deadlines(unfiled, trim, rules_for(2026))]
    assert "File petition (DR-486) with the VAB" in names and "VAB hearing" not in names

    ics = to_ics(build_deadlines(case, trim, rules_for(2026)), case.folio)
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == 5


def test_connector_can_be_swapped_independently():
    class OnlyRecentSales(MockSales):
        name = "test double"

        def find_sales(self, near_lat, near_lon, radius_mi, start, end):
            return super().find_sales(near_lat, near_lon, radius_mi, date(2025, 7, 1), end)

    base = build_connectors()
    swapped = Connectors(base.property_records, OnlyRecentSales(), base.trim_notices, base.narrative)
    packet = generate_packet(load_case("strong_case.json"), swapped)
    assert all(c.sale.sale_date >= date(2025, 7, 1) for c in packet.valuation.comps)
    assert packet.data_sources["sales"] == "test double"


def test_unknown_connector_rejected():
    with pytest.raises(ValueError):
        build_connectors(sales="nope")


def test_write_outputs(tmp_path, connectors):
    packet = generate_packet(load_case("strong_case.json"), connectors)
    files = write_outputs(packet, tmp_path, pdf=False)
    evidence = files["evidence_html"].read_text()
    guide = files["owner_guide_html"].read_text()
    assert "Comparable Sales Grid" in evidence and "MOCK DATA" in evidence
    # Owner-only content (recommendation, savings, script) must not leak into the VAB evidence.
    assert "Should you appeal" not in evidence and "Hearing script" not in evidence
    assert "Should you appeal" in guide
    assert json.loads(files["petition"].read_text())["Parcel ID (folio)"] == packet.property.folio
