"""Go / no-go: does an appeal actually lower this homeowner's tax bill?"""

from __future__ import annotations

from .models import Decision, Recommendation, TrimNotice, ValuationResult
from .rules import TaxYearRules

MIN_WORTHWHILE_SAVINGS = 150


def decide(valuation: ValuationResult, trim: TrimNotice, rules: TaxYearRules) -> Decision:
    reasons: list[str] = []
    exemptions = trim.assessed_value - trim.taxable_value
    jv_reduction = max(0, trim.just_value - valuation.requested_just_value)

    cap_issue = next((a for a in valuation.audits if a.code == "cap_exceeded"), None)
    corrected_assessed = trim.assessed_value - (cap_issue.amount if cap_issue else 0)
    if jv_reduction:
        new_assessed = min(corrected_assessed, valuation.requested_just_value)
    else:
        new_assessed = corrected_assessed
    new_taxable = max(0, new_assessed - exemptions)
    taxable_reduction = trim.taxable_value - new_taxable
    savings = round(taxable_reduction * trim.total_millage / 1000)

    if jv_reduction:
        reasons.append(f"Comparable sales support a just value of ${valuation.requested_just_value:,}, "
                       f"${jv_reduction:,} below the Property Appraiser's ${trim.just_value:,}.")
    if cap_issue:
        reasons.append(cap_issue.message)

    if savings <= 0:
        rec = Recommendation.NO_GO
        if jv_reduction and trim.assessed_value <= valuation.requested_just_value:
            reasons.append(
                f"Your assessed value (${trim.assessed_value:,}) is already capped below the supported "
                f"just value, so lowering just value would not change your taxable value or your "
                f"tax bill this year. It can still matter later, because the gap between just and "
                f"assessed value is what portability lets you carry to a new home."
            )
        elif not jv_reduction:
            reasons.append("The assessment is at or below what comparable sales support.")
    elif cap_issue:
        rec = Recommendation.GO
        reasons.append("Assessment cap errors are objective and usually corrected without dispute.")
    elif savings >= max(MIN_WORTHWHILE_SAVINGS, 10 * rules.filing_fee_per_folio) and valuation.confidence != "low":
        rec = Recommendation.GO
    else:
        rec = Recommendation.MAYBE
        if valuation.confidence == "low":
            reasons.append("Comparable sales are thin or widely spread, so the case is weaker.")
        else:
            reasons.append("Estimated savings are small relative to the effort of a hearing.")

    if savings > 0:
        reasons.append(f"Estimated savings: about ${savings:,}/year at {trim.total_millage} mills, "
                       f"for a ${rules.filing_fee_per_folio} filing fee.")

    return Decision(
        recommendation=rec,
        just_value_reduction=jv_reduction,
        new_assessed_value=new_assessed,
        new_taxable_value=new_taxable,
        taxable_reduction=taxable_reduction,
        estimated_annual_savings=savings,
        filing_fee=rules.filing_fee_per_folio,
        reasons=reasons,
    )
