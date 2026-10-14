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

### Web UI

```bash
taxappeal serve          # then open http://127.0.0.1:8000
```

Fill in the form (property, owner, hearing date, optional repair estimates). The results page shows the recommendation, savings, key dates and comparable sales, with links to the evidence packet, owner guide, calendar file and petition worksheet. Runs are saved under `out/web/`. The server only runs locally and uses the standard library (no extra dependencies).

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

## Data connectors

Each external dependency is a `Protocol` in `src/taxappeal/connectors/base.py`, chosen per run with command-line flags or `TAXAPPEAL_CONNECTORS`:

| Connector | Implementations | Status |
|---|---|---|
| `property_records` | `mock`, **`dor`** (FL DOR NAL roll) | Real data available |
| `sales` | `mock`, **`dor`** (FL DOR Sale Data File) | Real data available |
| `trim_notices` | `mock`, **`ocr`** (Claude reads the owner's TRIM notice) | Real; owner confirms the values |
| `narrative` | `template` | Template text. A Claude writer is planned and must pass the grounding check |

See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for field mappings and caveats.

### Using the state roll (`dor`)

1. Download Miami-Dade's (county 23) **NAL** and **SDF** CSV files from the [FL DOR data portal](https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx). Use the preliminary roll (July) for the current TRIM year.
2. Optional but recommended: a CSV of parcel coordinates (folio, latitude, longitude in WGS84), for example exported from Miami-Dade's GIS property point layer. Without it, comparable sales come from the subject's DOR neighborhood code instead of a distance search.
3. Build the local index (one time per roll):
   ```bash
   taxappeal import-dor --nal NAL23F202601.csv --sdf SDF23F202601.csv --coords parcel_points.csv
   ```
   This writes `data/dor.sqlite` (override with `--db` or `TAXAPPEAL_DOR_DB`). The importer checks the column headers and names any that are missing.
4. Use it:
   ```bash
   taxappeal generate case.json --property-records dor --sales dor
   TAXAPPEAL_CONNECTORS="property_records=dor,sales=dor,trim_notices=ocr" taxappeal serve
   ```

To try this without downloading anything, `examples/dor_sample/` holds small DOR-format files built from the fictional mock data. Run `python tests/dor_fixture.py examples/dor_sample` to regenerate them.

### Reading the TRIM notice (`ocr`)

```bash
pip install -e '.[ocr]'
export ANTHROPIC_API_KEY=...              # or `ant auth login`
taxappeal ocr samples/sample_trim_notice.pdf          # prints the values it read
taxappeal generate case.json --property-records dor --sales dor --trim-notice notice.pdf
```

In the web UI, the owner uploads the notice and clicks **Read my notice**. The values are filled into the form for the owner to check before building. The owner can also type the values in, which works without an API key. The folio read from the notice is cross-checked against the property, and differences from the roll are listed under "Please double-check".

## Not yet built

- Filling the official DR-486 PDF (the MVP produces a field worksheet to type into the VAB portal)
- Photo upload and exhibits, owner e-signature, a web UI
- Adjustment rates derived by regression on real neighborhood sales (`AdjustmentRates` defaults for now)
- Equity / uniformity exhibit, exemption and portability petitions
