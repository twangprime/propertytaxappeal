"""Deadline calendar and .ics export."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .models import CaseInput, Deadline, TrimNotice
from .rules import TaxYearRules


def build_deadlines(case: CaseInput, trim: TrimNotice, rules: TaxYearRules) -> list[Deadline]:
    petition_due = trim.petition_deadline or rules.petition_deadline or trim.mailing_date + timedelta(days=25)
    items = [] if case.petition_filed else [
        Deadline(
            name="Informal review with the Property Appraiser (optional)",
            due=petition_due,
            description="Ask the Property Appraiser to reconsider before filing. Bring the comparable sales.",
        ),
        Deadline(
            name="File petition (DR-486) with the VAB",
            due=petition_due,
            description=f"File online via the Clerk's VAB portal. ${rules.filing_fee_per_folio} fee per folio.",
            verified=rules.petition_deadline is not None,
        ),
    ]
    if case.hearing_date:
        h = case.hearing_date
        items += [
            Deadline(
                name="Send your evidence to the Property Appraiser",
                due=h - timedelta(days=rules.evidence_to_pa_days_before_hearing),
                description="Required if you asked for the Property Appraiser's evidence (Fla. Stat. 194.011(4)).",
            ),
            Deadline(
                name="Property Appraiser's evidence due to you",
                due=h - timedelta(days=rules.pa_evidence_days_before_hearing),
                description="Review it and update your rebuttal notes.",
            ),
            Deadline(
                name="Upload evidence to the VAB portal",
                due=h - timedelta(days=rules.upload_days_before_hearing),
                description="Upload the evidence packet PDF (reported 9:00 AM cutoff; confirm with the Clerk).",
                verified=rules.upload_deadline_verified,
            ),
            Deadline(name="VAB hearing", due=h, description="Special Magistrate hearing."),
        ]
    items.append(Deadline(
        name="Pay at least 75% of taxes",
        due=date(trim.tax_year + 1, 3, 31),
        description="Required while the petition is pending, or the petition is denied (Fla. Stat. 194.014).",
    ))
    return sorted(items, key=lambda d: d.due)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(deadlines: list[Deadline], folio: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//taxappeal//EN", "CALSCALE:GREGORIAN"]
    for i, d in enumerate(deadlines):
        note = "" if d.verified else " (UNVERIFIED - confirm with the Clerk)"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{folio}-{i}-{d.due:%Y%m%d}@taxappeal",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.due:%Y%m%d}",
            f"DTEND;VALUE=DATE:{d.due + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(d.name + note)}",
            f"DESCRIPTION:{_escape(f'Folio {folio}. {d.description}')}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
