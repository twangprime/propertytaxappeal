"""DR-486 petition worksheet: the values a homeowner types into the VAB portal.

The MVP emits a field worksheet rather than a filled PDF. Filling the official PDF is a
later connector once the final form version and field map are confirmed.
"""

from __future__ import annotations

from .models import CaseInput, Decision, PropertyRecord, PropertyUse, TrimNotice, ValuationResult
from .rules import TaxYearRules


def petition_fields(
    case: CaseInput,
    prop: PropertyRecord,
    trim: TrimNotice,
    valuation: ValuationResult,
    decision: Decision,
    rules: TaxYearRules,
) -> dict[str, str]:
    reasons = []
    if decision.just_value_reduction:
        reasons.append("Real property value (just value) is incorrect")
    if any(a.code == "cap_exceeded" for a in valuation.audits):
        reasons.append("Property assessment increase limitation (assessment cap) not applied correctly")
    property_type = {
        PropertyUse.SINGLE_FAMILY: "Residential, 1-4 units",
        PropertyUse.TOWNHOUSE: "Residential, 1-4 units",
        PropertyUse.CONDO: "Condominium",
    }[prop.building.use]
    return {
        "Form": rules.dr486_form_version,
        "County": "Miami-Dade",
        "Tax year": str(trim.tax_year),
        "Petitioner name": case.owner.name,
        "Petitioner type": "Taxpayer of record",
        "Mailing address": case.owner.mailing_address,
        "Phone": case.owner.phone,
        "Email": case.owner.email,
        "Parcel ID (folio)": prop.folio,
        "Physical address": prop.address,
        "Property type": property_type,
        "Value from TRIM notice (just value)": f"${trim.just_value:,}",
        "Petitioner's estimate of value": f"${valuation.requested_just_value:,}",
        "Reason(s) for petition": "; ".join(reasons) or "None identified",
        "Request Property Appraiser's evidence (194.011(4)(a))": "Yes",
        "Hearing preference": "Owner to choose (in person or virtual)",
        "Agent": "None (owner filing)",
        "Filing fee": f"${rules.filing_fee_per_folio}",
        "Signature": "Owner must sign and date (not completed by this tool)",
    }
