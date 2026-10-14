"""End-to-end: case input -> Packet -> files on disk."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .connectors import Connectors
from .deadlines import build_deadlines, to_ics
from .decision import decide
from .models import CaseInput, Packet, PropertyRecord, TrimNotice
from .narrative import check_numbers_grounded
from .petition import petition_fields
from .render import render_evidence_html, render_owner_guide_html, render_pdf
from .rules import rules_for
from .valuation import value_property


class UngroundedNarrativeError(RuntimeError):
    pass


def normalize_folio(folio: str) -> str:
    return "".join(ch for ch in folio if ch.isdigit())


def cross_check(prop: PropertyRecord, trim: TrimNotice) -> list[str]:
    """Compare the TRIM notice with the property record. Mismatched folios are fatal."""
    if normalize_folio(trim.folio) != normalize_folio(prop.folio):
        raise ValueError(f"TRIM notice is for folio {trim.folio}, not {prop.folio}")
    warnings = []
    current = prop.assessment_for(trim.tax_year)
    if current is None:
        warnings.append(f"The property record has no {trim.tax_year} values to compare with the TRIM notice.")
    else:
        for label, a, b in [("just value", trim.just_value, current.just_value),
                            ("assessed value", trim.assessed_value, current.assessed_value)]:
            if a != b:
                warnings.append(f"TRIM notice {label} (${a:,}) differs from the property record (${b:,}). "
                                f"The TRIM notice value is used; double-check it.")
    return warnings


def generate_packet(case: CaseInput, connectors: Connectors) -> Packet:
    rules = rules_for(case.tax_year)
    prop = connectors.property_records.get_property(case.folio)
    trim = case.trim_notice or connectors.trim_notices.get_trim_notice(case)
    warnings = cross_check(prop, trim)
    valuation = value_property(prop, trim, case, connectors.sales, rules)
    decision = decide(valuation, trim, rules)
    narrative = connectors.narrative.write(case, prop, valuation, decision)
    ungrounded = check_numbers_grounded(narrative, valuation, decision)
    if ungrounded:
        raise UngroundedNarrativeError(f"Narrative cites figures not in the valuation: {ungrounded}")
    deadlines = build_deadlines(case, trim, rules)
    petition_due = next((d.due for d in deadlines if d.name.startswith("File petition")), None)
    if petition_due and petition_due < date.today():
        warnings.append(
            f"The {trim.tax_year} petition deadline ({petition_due:%B %d, %Y}) has passed. A late petition is "
            f"accepted only for good cause, so contact the VAB clerk before relying on this packet."
        )
    return Packet(
        case=case,
        property=prop,
        trim=trim,
        valuation=valuation,
        decision=decision,
        deadlines=deadlines,
        narrative=narrative,
        petition_fields=petition_fields(case, prop, trim, valuation, decision, rules),
        data_sources={
            **connectors.describe(),
            **({"trim_notices": "owner-confirmed TRIM values"} if case.trim_notice else {}),
        },
        warnings=warnings,
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
