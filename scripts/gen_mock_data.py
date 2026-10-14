"""Generate deterministic mock data for the MVP connectors.

All parcels, addresses and owners are fictional. Prices follow a simple hedonic model per
neighborhood so the valuation engine produces plausible results.

    python scripts/gen_mock_data.py  # writes src/taxappeal/mock_data/mock_data.json
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/taxappeal/mock_data/mock_data.json"
VALUATION_DATE = date(2026, 1, 1)
rng = random.Random(20260101)

NEIGHBORHOODS = {
    "Westchester (mock)": dict(
        center=(25.7480, -80.3330), municipality="Unincorporated Miami-Dade",
        use="single_family", psf=330, lot_rate=14, pool=35000, year_rate=1200,
        trend=0.0025, sqft=(1300, 2600), lot=(6000, 10000), years=(1952, 1990),
    ),
    "Kendall Lakes (mock)": dict(
        center=(25.6950, -80.4090), municipality="Unincorporated Miami-Dade",
        use="single_family", psf=300, lot_rate=12, pool=30000, year_rate=1000,
        trend=0.0020, sqft=(1500, 2800), lot=(5500, 9000), years=(1975, 2000),
    ),
    "Brickell (mock)": dict(
        center=(25.7600, -80.1930), municipality="City of Miami",
        use="condo", psf=560, lot_rate=0, pool=0, year_rate=2500,
        trend=0.0010, sqft=(700, 1500), lot=(0, 0), years=(2005, 2020),
    ),
}
STREETS = ["Mockingbird", "Placeholder", "Sample", "Testing", "Fixture", "Example", "Demo", "Stub"]


def hedonic_price(n: dict, b: dict, sale_date: date) -> float:
    base = n["psf"] * b["living_sqft"] + n["lot_rate"] * b["lot_sqft"]
    base += n["pool"] * b["pool"] + n["year_rate"] * (b["year_built"] - 1980)
    base *= 1 + 0.06 * (b["condition"] - 3)
    months_before = (VALUATION_DATE - sale_date).days / 30.44
    return base * (1 - n["trend"] * months_before)


def jitter_location(center: tuple[float, float], max_mi: float) -> tuple[float, float]:
    r = max_mi * math.sqrt(rng.random())
    theta = rng.random() * 2 * math.pi
    return (
        round(center[0] + (r / 69.0) * math.sin(theta), 5),
        round(center[1] + (r / (69.0 * math.cos(math.radians(center[0])))) * math.cos(theta), 5),
    )


def make_building(n: dict, **overrides) -> dict:
    b = dict(
        use=n["use"],
        living_sqft=rng.randrange(*n["sqft"], 10),
        lot_sqft=rng.randrange(*n["lot"], 50) if n["lot"][1] else 0,
        year_built=rng.randint(*n["years"]),
        bedrooms=rng.choice([2, 3, 3, 4]) if n["use"] != "condo" else rng.choice([1, 2, 2, 3]),
        bathrooms=rng.choice([1.0, 2.0, 2.0, 2.5, 3.0]),
        pool=n["use"] != "condo" and rng.random() < 0.3,
        waterfront=False,
        condition=rng.choice([2, 3, 3, 3, 4]),
    )
    b.update(overrides)
    return b


def folio(prefix: str, i: int) -> str:
    return f"{prefix}-{i // 100:03d}-{i % 100:04d}"


def gen_sales() -> list[dict]:
    sales = []
    for hood_i, (hood, n) in enumerate(NEIGHBORHOODS.items()):
        prefix = f"30-{4900 + hood_i}"
        for i in range(24):
            b = make_building(n)
            sale_date = VALUATION_DATE - timedelta(days=rng.randint(10, 560))
            price = hedonic_price(n, b, sale_date) * rng.uniform(0.94, 1.06)
            qualified = rng.random() > 0.15
            if not qualified:
                price *= rng.uniform(0.45, 0.8)  # foreclosures, related-party transfers
            lat, lon = jitter_location(n["center"], 1.6)
            street = rng.choice(STREETS)
            sales.append(dict(
                folio=folio(prefix, 100 + i),
                address=f"{rng.randint(100, 9999)} {street} {'Ave' if i % 2 else 'St'}, Miami, FL (MOCK)",
                sale_date=sale_date.isoformat(),
                price=int(round(price, -2)),
                qualified=qualified,
                building=b,
                location=dict(lat=lat, lon=lon, neighborhood=hood, municipality=n["municipality"]),
            ))
    return sales


def subject(hood: str, fol: str, address: str, homestead: bool, exemptions: int,
            jv: int, assessed: int, prior_assessed: int, prior_jv: int,
            last_sale_date: str | None = None, **bldg) -> dict:
    n = NEIGHBORHOODS[hood]
    b = make_building(n, **bldg)
    taxable = max(0, assessed - exemptions)
    return dict(
        folio=fol,
        address=address,
        building=b,
        location=dict(lat=n["center"][0], lon=n["center"][1], neighborhood=hood,
                      municipality=n["municipality"]),
        homestead=homestead,
        last_sale_date=last_sale_date,
        exemptions_total=exemptions,
        assessments=[
            dict(tax_year=2026, just_value=jv, assessed_value=assessed, taxable_value=taxable),
            dict(tax_year=2025, just_value=prior_jv, assessed_value=prior_assessed,
                 taxable_value=max(0, prior_assessed - exemptions)),
        ],
    )


def main() -> None:
    sales = gen_sales()
    properties = [
        # 1. Strong case: bought in 2025 (cap reset), PA overvalued, roof needs replacement.
        subject("Westchester (mock)", "30-4019-001-0100", "1200 Mockingbird St, Miami, FL 33155 (MOCK)",
                homestead=True, exemptions=50000, jv=655000, assessed=655000,
                prior_assessed=610000, prior_jv=640000, last_sale_date="2025-03-14",
                living_sqft=1850, lot_sqft=7500, year_built=1961, bedrooms=3, bathrooms=2.0,
                pool=False, condition=2),
        # 2. Fairly assessed condo: appeal not worth it.
        subject("Brickell (mock)", "30-4139-002-0450", "88 Sample Ave #1204, Miami, FL 33131 (MOCK)",
                homestead=False, exemptions=0, jv=455000, assessed=455000,
                prior_assessed=440000, prior_jv=440000,
                living_sqft=1010, year_built=2012, bedrooms=2, bathrooms=2.0, condition=3),
        # 3. Cap error: long-time homestead, PA raised assessed value 10% instead of the SOH cap.
        subject("Kendall Lakes (mock)", "30-5911-003-0780", "15400 Fixture Ln, Miami, FL 33186 (MOCK)",
                homestead=True, exemptions=50000, jv=640000, assessed=330000,
                prior_assessed=300000, prior_jv=600000,
                living_sqft=2100, lot_sqft=7200, year_built=1986, bedrooms=4, bathrooms=2.5,
                pool=True, condition=3),
        # 4. Over-valued but SOH-protected: just value is high, but the capped assessed value is far
        #    below any fair just value, so the appeal saves nothing this year.
        subject("Kendall Lakes (mock)", "30-5911-003-0910", "15520 Fixture Ln, Miami, FL 33186 (MOCK)",
                homestead=True, exemptions=50000, jv=720000, assessed=262650,
                prior_assessed=255000, prior_jv=640000,
                living_sqft=1950, lot_sqft=7000, year_built=1982, bedrooms=3, bathrooms=2.0,
                pool=False, condition=3),
    ]
    millage = {"Westchester (mock)": 18.9, "Kendall Lakes (mock)": 18.9, "Brickell (mock)": 20.4}
    trims = []
    for p in properties:
        cur, prev = p["assessments"]
        trims.append(dict(
            folio=p["folio"], tax_year=2026, mailing_date="2026-08-24",
            just_value=cur["just_value"], assessed_value=cur["assessed_value"],
            taxable_value=cur["taxable_value"], prior_assessed_value=prev["assessed_value"],
            total_millage=millage[p["location"]["neighborhood"]],
        ))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"_note": "Fictional data for development only.", "properties": properties,
         "sales": sales, "trim_notices": trims}, indent=1))
    print(f"wrote {OUT} ({len(properties)} properties, {len(sales)} sales)")


if __name__ == "__main__":
    main()
