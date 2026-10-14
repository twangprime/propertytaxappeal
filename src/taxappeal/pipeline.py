"""End-to-end: case input -> Packet -> files on disk."""

from __future__ import annotations

import json
from pathlib import Path

from .connectors import Connectors
from .deadlines import build_deadlines, to_ics
from .decision import decide
from .models import CaseInput, Packet
from .narrative import check_numbers_grounded
from .petition import petition_fields
from .render import render_evidence_html, render_owner_guide_html, render_pdf
from .rules import rules_for
from .valuation import value_property


class UngroundedNarrativeError(RuntimeError):
    pass


def generate_packet(case: CaseInput, connectors: Connectors) -> Packet:
    rules = rules_for(case.tax_year)
    prop = connectors.property_records.get_property(case.folio)
    trim = connectors.trim_notices.get_trim_notice(case.folio, case.tax_year)
    valuation = value_property(prop, trim, case, connectors.sales, rules)
    decision = decide(valuation, trim, rules)
    narrative = connectors.narrative.write(case, prop, valuation, decision)
    ungrounded = check_numbers_grounded(narrative, valuation, decision)
    if ungrounded:
        raise UngroundedNarrativeError(f"Narrative cites figures not in the valuation: {ungrounded}")
    return Packet(
        case=case,
        property=prop,
        trim=trim,
        valuation=valuation,
        decision=decision,
        deadlines=build_deadlines(case, trim, rules),
        narrative=narrative,
        petition_fields=petition_fields(case, prop, trim, valuation, decision, rules),
        data_sources=connectors.describe(),
    )


def write_outputs(packet: Packet, out_dir: Path, pdf: bool = True) -> dict[str, Path]:
    """Write the evidence packet (for the VAB), the owner guide (private), and supporting files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "evidence_html": out_dir / "evidence.html",
        "owner_guide_html": out_dir / "owner_guide.html",
        "packet_json": out_dir / "packet.json",
        "petition": out_dir / "dr486_worksheet.json",
        "calendar": out_dir / "deadlines.ics",
    }
    files["evidence_html"].write_text(render_evidence_html(packet))
    files["owner_guide_html"].write_text(render_owner_guide_html(packet))
    files["packet_json"].write_text(packet.model_dump_json(indent=2))
    files["petition"].write_text(json.dumps(packet.petition_fields, indent=2))
    files["calendar"].write_text(to_ics(packet.deadlines, packet.property.folio))
    if pdf:
        for key in ("evidence", "owner_guide"):
            pdf_path = render_pdf(files[f"{key}_html"], out_dir / f"{key}.pdf")
            if pdf_path:
                files[f"{key}_pdf"] = pdf_path
    return files
