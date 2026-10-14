"""Sales-comparison valuation engine. Fully deterministic: every figure in the packet comes
from here, never from the narrative layer."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from .connectors.base import SalesSource
from .geo import distance_mi
from .models import (
    Adjustment,
    AuditFinding,
    Building,
    CaseInput,
    Comparable,
    Location,
    PropertyRecord,
    PropertyUse,
    Sale,
    TrimNotice,
    ValuationResult,
)
from .rules import TaxYearRules

LOOKBACK_DAYS = 548  # ~18 months before the Jan 1 valuation date
SEARCH_RADII_MI = (0.75, 1.0, 1.5, 2.0)
MIN_COMPS = 3
MAX_COMPS = 5


@dataclass(frozen=True)
class AdjustmentRates:
    """Default adjustment rates. Later: derive per neighborhood from regression on real sales."""

    area_rate_factor: float = 0.6  # share of median comp $/sqft applied to living-area differences
    lot_per_sqft: int = 10
    per_year_built: int = 1000
    pool: int = 30000
    per_bathroom: int = 10000
    condition_pct_per_step: float = 0.05
    max_monthly_trend: float = 0.01


def _distance(a: Location, b: Location) -> float | None:
    if a.has_coords and b.has_coords:
        return distance_mi(a.lat, a.lon, b.lat, b.lon)
    return None


def _months_between(earlier: date, later: date) -> float:
    return (later - earlier).days / 30.44


def _is_candidate(subject: Building, comp: Building) -> bool:
    if comp.use != subject.use:
        return False
    if abs(comp.living_sqft - subject.living_sqft) > 0.25 * subject.living_sqft:
        return False
    year_tolerance = 10 if subject.use == PropertyUse.CONDO else 15
    if abs(comp.year_built - subject.year_built) > year_tolerance:
        return False
    if subject.lot_sqft and abs(comp.lot_sqft - subject.lot_sqft) > 0.4 * subject.lot_sqft:
        return False
    return True


def _similarity_score(subject: PropertyRecord, sale: Sale, valuation_date: date) -> float:
    """Lower is more similar."""
    s, c = subject.building, sale.building
    dist = _distance(subject.location, sale.location)
    # Without coordinates the sales source already limited sales to the subject's neighborhood.
    score = dist if dist is not None else 0.5
    score += 4 * abs(c.living_sqft - s.living_sqft) / s.living_sqft
    score += abs(c.year_built - s.year_built) / 15
    score += 0.5 * _months_between(sale.sale_date, valuation_date) / 18
    if c.pool is not None and s.pool is not None:
        score += 0.3 * (c.pool != s.pool)
    score += 0.2 * abs(c.condition - s.condition)
    return score


def estimate_monthly_trend(sales: list[Sale], valuation_date: date, cap: float) -> float:
    """Least-squares slope of $/sqft over time, as a monthly % change. 0 if too few sales."""
    if len(sales) < 8:
        return 0.0
    xs = [-_months_between(s.sale_date, valuation_date) for s in sales]
    ys = [s.price / s.building.living_sqft for s in sales]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return 0.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return max(-cap, min(cap, slope / my))


def _adjust(
    subject: Building,
    sale: Sale,
    months: float,
    trend: float,
    area_rate: float,
    rates: AdjustmentRates,
    subject_condition: int,
) -> list[Adjustment]:
    c = sale.building
    adjustments: list[Adjustment] = []

    def add(factor: str, amount: float, explanation: str) -> None:
        amount = int(round(amount, -2))
        if amount:
            adjustments.append(Adjustment(factor=factor, amount=amount, explanation=explanation))

    add("Market conditions", sale.price * trend * months,
        f"{months:.1f} months before Jan 1 at {trend * 100:+.2f}%/month")
    time_adjusted = sale.price + sum(a.amount for a in adjustments)
    add("Living area", (subject.living_sqft - c.living_sqft) * area_rate,
        f"{subject.living_sqft - c.living_sqft:+,} sqft at ${area_rate:,.0f}/sqft")
    if subject.lot_sqft:
        add("Lot size", (subject.lot_sqft - c.lot_sqft) * rates.lot_per_sqft,
            f"{subject.lot_sqft - c.lot_sqft:+,} sqft at ${rates.lot_per_sqft}/sqft")
    add("Year built", (subject.year_built - c.year_built) * rates.per_year_built,
        f"{subject.year_built - c.year_built:+} years at ${rates.per_year_built:,}/year")
    if subject.use != PropertyUse.CONDO and None not in (subject.pool, c.pool) and subject.pool != c.pool:
        add("Pool", rates.pool if subject.pool else -rates.pool,
            "Subject has a pool" if subject.pool else "Comparable has a pool; subject does not")
    if subject.bathrooms is not None and c.bathrooms is not None:
        add("Bathrooms", (subject.bathrooms - c.bathrooms) * rates.per_bathroom,
            f"{subject.bathrooms - c.bathrooms:+g} baths at ${rates.per_bathroom:,}")
    add("Condition", time_adjusted * rates.condition_pct_per_step * (subject_condition - c.condition),
        f"Subject condition {subject_condition} vs comparable {c.condition} (1-5 scale)")
    return adjustments


def _audits(
    prop: PropertyRecord,
    trim: TrimNotice,
    case: CaseInput,
    rules: TaxYearRules,
    adjusted_market_value: int,
    requested_just_value: int,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    implied_ratio = trim.just_value / adjusted_market_value if adjusted_market_value else 0
    if trim.just_value > requested_just_value:
        findings.append(AuditFinding(
            code="overvalued",
            severity="issue",
            message=(
                f"The Property Appraiser's just value is {implied_ratio:.0%} of the market value "
                f"indicated by comparable sales. After the {rules.cost_of_sale_pct:.0%} cost-of-sale "
                f"adjustment required by Fla. Stat. 193.011(8), just value should not exceed "
                f"${requested_just_value:,}."
            ),
            amount=trim.just_value - requested_just_value,
        ))
    else:
        findings.append(AuditFinding(
            code="value_supported",
            severity="info",
            message=(
                f"The Property Appraiser's just value (${trim.just_value:,}) is at or below the "
                f"value supported by comparable sales (${requested_just_value:,})."
            ),
        ))

    cap = rules.homestead_cap_pct if prop.homestead else rules.non_homestead_cap_pct
    cap_label = "Save Our Homes" if prop.homestead else "non-homestead"
    sold_last_year = prop.last_sale_date is not None and prop.last_sale_date.year == trim.tax_year - 1
    if sold_last_year:
        findings.append(AuditFinding(
            code="cap_reset",
            severity="info",
            message=(
                f"The property sold on {prop.last_sale_date:%B %d, %Y}, so the assessment cap reset "
                f"and assessed value equals just value for {trim.tax_year}."
            ),
        ))
    elif trim.prior_assessed_value is None:
        findings.append(AuditFinding(
            code="cap_not_checked",
            severity="info",
            message="Last year's assessed value is unknown, so the assessment cap was not checked.",
        ))
    elif case.recent_improvements:
        findings.append(AuditFinding(
            code="cap_not_checked",
            severity="info",
            message="Owner reported recent improvements, which may lawfully increase assessed value "
            "beyond the cap. The cap check was skipped.",
        ))
    else:
        allowed = min(round(trim.prior_assessed_value * (1 + cap)), trim.just_value)
        if trim.assessed_value > allowed:
            findings.append(AuditFinding(
                code="cap_exceeded",
                severity="issue",
                message=(
                    f"Assessed value rose from ${trim.prior_assessed_value:,} to "
                    f"${trim.assessed_value:,} "
                    f"({trim.assessed_value / trim.prior_assessed_value - 1:+.1%}), above the "
                    f"{cap:.0%} {cap_label} cap. Assessed value should not exceed ${allowed:,}."
                ),
                amount=trim.assessed_value - allowed,
                figures={"prior_assessed_value": trim.prior_assessed_value, "allowed_assessed_value": allowed},
            ))
        else:
            findings.append(AuditFinding(
                code="cap_ok",
                severity="info",
                message=f"Assessed value increase is within the {cap:.0%} {cap_label} cap.",
            ))
    return findings


def _confidence(comps: list[Comparable], cv: float) -> str:
    avg_gross = statistics.fmean(c.gross_adjustment_pct for c in comps)
    if len(comps) >= 4 and cv <= 0.06 and avg_gross <= 0.20:
        return "high"
    if len(comps) >= MIN_COMPS and cv <= 0.12 and avg_gross <= 0.30:
        return "medium"
    return "low"


def value_property(
    prop: PropertyRecord,
    trim: TrimNotice,
    case: CaseInput,
    sales_source: SalesSource,
    rules: TaxYearRules,
    rates: AdjustmentRates = AdjustmentRates(),
) -> ValuationResult:
    valuation_date = date(trim.tax_year, 1, 1)
    start = valuation_date - timedelta(days=LOOKBACK_DAYS)
    end = valuation_date - timedelta(days=1)
    market = [
        s for s in sales_source.find_sales(prop, max(SEARCH_RADII_MI), start, end)
        if s.qualified and s.building.use == prop.building.use and s.folio != prop.folio
    ]
    candidates: list[Sale] = []
    for radius in SEARCH_RADII_MI:
        candidates = [
            s for s in market
            if _is_candidate(prop.building, s.building)
            and (_distance(prop.location, s.location) or 0) <= radius
        ]
        if len(candidates) >= MAX_COMPS:
            break
    if len(candidates) < MIN_COMPS:
        raise ValueError(
            f"Only {len(candidates)} comparable sales found for {prop.folio}; at least {MIN_COMPS} needed"
        )

    chosen = sorted(candidates, key=lambda s: _similarity_score(prop, s, valuation_date))[:MAX_COMPS]
    trend = estimate_monthly_trend(market, valuation_date, rates.max_monthly_trend)
    median_psf = statistics.median(s.price / s.building.living_sqft for s in chosen)
    area_rate = round(median_psf * rates.area_rate_factor)
    # Documented repairs are deducted separately, so treat the subject as average condition
    # in the comparison to avoid counting the same defects twice.
    subject_condition = 3 if case.repair_estimates else prop.building.condition

    comps: list[Comparable] = []
    for sale in chosen:
        months = _months_between(sale.sale_date, valuation_date)
        adjustments = _adjust(prop.building, sale, months, trend, area_rate, rates, subject_condition)
        net = sum(a.amount for a in adjustments)
        gross = sum(abs(a.amount) for a in adjustments)
        dist = _distance(prop.location, sale.location)
        comps.append(Comparable(
            sale=sale,
            distance_mi=round(dist, 2) if dist is not None else None,
            months_before_valuation=round(months, 1),
            adjustments=adjustments,
            adjusted_price=int(round(sale.price + net, -2)),
            gross_adjustment_pct=round(gross / sale.price, 4),
            net_adjustment_pct=round(net / sale.price, 4),
            weight=0.0,
            selection_reason=(
                f"Qualified sale {f'{dist:.2f} mi away' if dist is not None else 'in the same neighborhood'}, "
                f"{round(months)} month{'' if round(months) == 1 else 's'} before Jan 1, "
                f"{sale.building.living_sqft:,} sqft built {sale.building.year_built}"
            ),
        ))

    raw = [1 / (c.gross_adjustment_pct + 0.05) for c in comps]
    for c, w in zip(comps, raw):
        c.weight = round(w / sum(raw), 4)
    indicated = int(round(sum(c.adjusted_price * c.weight for c in comps), -3))
    repair = sum(r.amount for r in case.repair_estimates)
    adjusted_market = indicated - repair
    requested = int(round(adjusted_market * (1 - rules.cost_of_sale_pct), -3))
    prices = [c.adjusted_price for c in comps]
    cv = statistics.pstdev(prices) / statistics.fmean(prices)

    return ValuationResult(
        folio=prop.folio,
        tax_year=trim.tax_year,
        valuation_date=valuation_date,
        comps=comps,
        indicated_market_value=indicated,
        repair_deduction=repair,
        adjusted_market_value=adjusted_market,
        cost_of_sale_pct=rules.cost_of_sale_pct,
        requested_just_value=requested,
        current_just_value=trim.just_value,
        current_assessed_value=trim.assessed_value,
        current_taxable_value=trim.taxable_value,
        adjusted_price_low=min(prices),
        adjusted_price_high=max(prices),
        coefficient_of_variation=round(cv, 4),
        audits=_audits(prop, trim, case, rules, adjusted_market, requested),
        confidence=_confidence(comps, cv),
    )
