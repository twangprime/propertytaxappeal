"""Packet prose. The template writer is the mock; an LLM writer must pass the same
``check_numbers_grounded`` validation so it cannot introduce figures of its own."""

from __future__ import annotations

import re

from .models import (
    CaseInput,
    Decision,
    Narrative,
    PropertyRecord,
    Recommendation,
    ValuationResult,
)

_DOLLAR = re.compile(r"\$\s?([\d,]+)")


def allowed_amounts(valuation: ValuationResult, decision: Decision) -> set[int]:
    """Every dollar figure the narrative is allowed to cite."""

    def collect(obj: object, out: set[int]) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, int):
            out.add(abs(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                collect(v, out)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                collect(v, out)

    out: set[int] = set()
    collect(valuation.model_dump(), out)
    collect(decision.model_dump(), out)
    return out


def check_numbers_grounded(narrative: Narrative, valuation: ValuationResult, decision: Decision) -> list[str]:
    """Return dollar amounts in the narrative that don't appear in the valuation/decision data."""
    allowed = allowed_amounts(valuation, decision)
    texts = [narrative.one_line_argument, narrative.summary, narrative.hearing_script,
             *narrative.comp_explanations.values(), *(t for pair in narrative.rebuttals for t in pair)]
    bad = []
    for text in texts:
        for m in _DOLLAR.finditer(text):
            if int(m.group(1).replace(",", "")) not in allowed:
                bad.append(m.group(0))
    return bad


class TemplateNarrativeWriter:
    name = "template"

    def write(
        self,
        case: CaseInput,
        prop: PropertyRecord,
        valuation: ValuationResult,
        decision: Decision,
    ) -> Narrative:
        v, d = valuation, decision
        cap_issue = next((a for a in v.audits if a.code == "cap_exceeded"), None)
        n = len(v.comps)

        if cap_issue and not d.just_value_reduction:
            one_line = (f"The assessed value exceeds the statutory cap by ${cap_issue.amount:,} "
                        f"and should be corrected.")
        else:
            one_line = (f"Comparable sales support a just value of ${v.requested_just_value:,}, "
                        f"not ${v.current_just_value:,}.")

        parts = [
            f"The Property Appraiser set the {v.tax_year} just value of {prop.address} at "
            f"${v.current_just_value:,}. {n} qualified sales of similar "
            f"{prop.building.use.value.replace('_', ' ')} properties nearby, adjusted for differences "
            f"and to the January 1 valuation date, indicate a market value of "
            f"${v.indicated_market_value:,} (adjusted range ${v.adjusted_price_low:,} to "
            f"${v.adjusted_price_high:,})."
        ]
        if v.repair_deduction:
            parts.append(f"Documented repairs needed as of January 1 total ${v.repair_deduction:,}, "
                         f"bringing market value to ${v.adjusted_market_value:,}.")
        parts.append(f"Applying the {v.cost_of_sale_pct:.0%} cost-of-sale adjustment under "
                     f"Fla. Stat. 193.011(8) gives a just value of ${v.requested_just_value:,}.")
        if cap_issue:
            parts.append(cap_issue.message)
        summary = " ".join(parts)

        comp_explanations = {c.sale.folio: c.selection_reason for c in v.comps}

        script_lines = [
            f"Good morning. I'm {case.owner.name}, owner of folio {prop.folio}.",
            one_line,
            f"My evidence uses {n} qualified, arm's-length sales from the 18 months before "
            f"January 1, {v.tax_year}, all of the same property type and close by.",
            f"After adjustments, they indicate ${v.indicated_market_value:,}.",
        ]
        if v.repair_deduction:
            script_lines.append(f"The house needed ${v.repair_deduction:,} of repairs on January 1; "
                                f"the estimates are in my exhibits.")
        script_lines.append(f"With the required cost-of-sale adjustment, that is "
                            f"${v.requested_just_value:,}, which I ask the Magistrate to adopt.")
        if cap_issue:
            script_lines.append(f"Separately, the assessed value is ${cap_issue.amount:,} above the cap "
                                f"and should be reduced regardless of just value.")
        script_lines.append("Thank you. I'm happy to answer questions.")

        rebuttals = [
            ("Your comparables are not similar to the subject.",
             "Each sale is a qualified sale of the same property type, filtered to within 25% of the "
             "subject's living area and 15 years of its age, with every adjustment shown in the grid."),
            ("The sales are too old.",
             "Every sale closed within 18 months of January 1 and is time-adjusted to that date using "
             "the neighborhood trend."),
            ("Our mass-appraisal model already considers these sales.",
             "The burden is whether the just value reflects market value for this specific property. "
             "The adjusted sales show it does not."),
        ]
        if v.repair_deduction:
            rebuttals.append((
                "The condition issues are not reflected in a sale.",
                "Buyers deduct repair costs from what they pay. The contractor estimates document the "
                "cost a buyer would face on January 1."))
        if d.recommendation == Recommendation.NO_GO:
            script_lines = ["(Not recommended to proceed to hearing; see the recommendation section.)"]

        return Narrative(
            one_line_argument=one_line,
            summary=summary,
            comp_explanations=comp_explanations,
            hearing_script="\n".join(script_lines),
            rebuttals=rebuttals,
        )
