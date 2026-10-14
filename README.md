# Miami-Dade Property Tax Appeal Packet Generator

Generates a Value Adjustment Board (VAB) appeal packet for a Miami-Dade **homeowner**:

| Output | Audience | Contents |
|---|---|---|
| `evidence.pdf` / `.html` | VAB magistrate and Property Appraiser | Cover, subject property, comparable sales grid with adjustments, location map, reconciliation with the 15% cost-of-sale adjustment, repair estimates, assessment-cap review |
| `owner_guide.pdf` / `.html` | Homeowner only | Go / no-go recommendation with estimated savings, key dates, DR-486 petition worksheet, hearing script, rebuttal prep, checklist |
| `deadlines.ics` | Homeowner | Calendar of filing, evidence-exchange, upload, hearing and payment deadlines |
| `dr486_worksheet.json`, `packet.json` | Integrations | Petition fields and the full structured packet |

Sample output (mock data): [`samples/`](samples/). See [`docs/SCOPE.md`](docs/SCOPE.md) for the product scope and background.

> **Status: MVP on mock data.** Every connector is a mock backed by fictional data in
> `src/taxappeal/mock_data/mock_data.json`. Outputs carry a "MOCK DATA, not for filing" banner.

## Quick start

```bash
pip install -e '.[dev]'
taxappeal list-mock                                  # folios in the mock data
taxappeal generate examples/strong_case.json         # writes out/<folio>/
pytest
```

PDFs are printed with headless Chromium. Set `CHROMIUM_PATH` if it isn't found automatically, or pass `--no-pdf`.

### Example scenarios

| Case file | Scenario | Expected result |
|---|---|---|
| `strong_case.json` | Recent buyer, house overvalued, roof and plumbing repairs documented | **GO**: about $87k just-value reduction |
| `cap_error.json` | Long-time homestead whose assessed value rose 10% instead of the 3% Save Our Homes cap | **GO**: objective cap error |
| `fair_condo.json` | Condo assessed below what sales support | **NO-GO** |
| `soh_protected.json` | Just value is too high, but the capped assessed value is far below it | **NO-GO**: no tax savings (explains portability) |

## How it works

```
CaseInput ─▶ PropertyRecordSource ─┐
          ─▶ TrimNoticeSource ─────┼─▶ valuation.py ─▶ decision.py ─▶ NarrativeWriter ─▶ grounding check ─▶ render
             SalesSource ──────────┘   (comps, adjustments,  (savings,      (prose only)     (every $ figure must
                                        audits)               go/no-go)                      exist in the data)
```

- **Deterministic math.** All figures come from `valuation.py` and `decision.py`. The narrative layer only writes prose. `narrative.check_numbers_grounded` rejects any packet whose text cites a dollar figure that isn't in the valuation or decision data, so an LLM writer can't make numbers up.
- **Per-year rules** (deadlines, fees, cap rates, form version) live in `rules.py`, not in code paths.

## Replacing mock connectors

Each external dependency is a `Protocol` in `src/taxappeal/connectors/base.py`. To replace one:

1. Implement the protocol in a new module, e.g. `connectors/dor_sdf.py`.
2. Register it in `REGISTRY` in `connectors/__init__.py`, e.g. `"sales": {"mock": MockSales, "dor_sdf": DorSdfSales}`.
3. Select it per run: `taxappeal generate case.json --sales dor_sdf`. The other connectors stay on mock.

| Connector | Mock today | Planned real implementation |
|---|---|---|
| `sales` (`SalesSource`) | Fictional sales | FL DOR Sale Data File (SDF) joined to the NAL roll, loaded into DuckDB |
| `property_records` (`PropertyRecordSource`) | Fictional parcels | Miami-Dade Property Appraiser data, plus Miami-Dade GIS for coordinates |
| `trim_notices` (`TrimNoticeSource`) | Fictional notices | OCR of the owner's uploaded TRIM notice (Claude vision), checked against the PA record |
| `narrative` (`NarrativeWriter`) | Template text | Claude, constrained to the `ValuationResult`. Must pass the grounding check |

Suggested order: **sales**, then **property records**, then **TRIM OCR**, then **narrative**. The first two decide valuation quality. The last two are convenience.

## Not yet built

- Filling the official DR-486 PDF (the MVP produces a field worksheet to type into the VAB portal)
- Photo upload and exhibits, owner e-signature, a web UI
- Adjustment rates derived by regression on real neighborhood sales (`AdjustmentRates` defaults for now)
- Equity / uniformity exhibit, exemption and portability petitions
