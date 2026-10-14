"""Per-tax-year rules. Forms, fees and deadlines change yearly, so keep them out of code paths.

Values marked ``verified=False`` come from secondary sources and must be confirmed with the
Miami-Dade Clerk / VAB before relying on them.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class TaxYearRules(BaseModel):
    tax_year: int
    petition_deadline: date | None  # official date if published; else TRIM mailing + 25 days
    filing_fee_per_folio: int = 15
    cost_of_sale_pct: float = 0.15  # Fla. Stat. 193.011(8) adjustment as applied by the PA
    homestead_cap_pct: float = 0.03  # Save Our Homes: lesser of 3% or CPI
    non_homestead_cap_pct: float = 0.10
    evidence_to_pa_days_before_hearing: int = 15  # Fla. Stat. 194.011(4)(a)
    pa_evidence_days_before_hearing: int = 7  # Fla. Stat. 194.011(4)(b)
    upload_days_before_hearing: int = 1
    upload_deadline_verified: bool = False  # third-party source only
    dr486_form_version: str = ""


RULES: dict[int, TaxYearRules] = {
    2026: TaxYearRules(
        tax_year=2026,
        petition_deadline=date(2026, 9, 18),  # Miami-Dade Clerk VAB page
        # 2026 SOH CPI cap not yet confirmed; 3% statutory ceiling used until verified.
        homestead_cap_pct=0.03,
        dr486_form_version="DR-486 (draft 07.15.26)",
    ),
    2027: TaxYearRules(tax_year=2027, petition_deadline=None, dr486_form_version="DR-486 (TBD)"),
}


def rules_for(tax_year: int) -> TaxYearRules:
    try:
        return RULES[tax_year]
    except KeyError:
        raise ValueError(f"No rules configured for tax year {tax_year}; add them to rules.py") from None
