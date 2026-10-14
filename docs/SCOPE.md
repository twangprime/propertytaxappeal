# Miami-Dade Property Tax Appeal Packet Generator — Scope

**Status:** Draft scope, 2026-10-14
**Goal:** Given a Miami-Dade folio number (or a photo/PDF of the TRIM notice), automatically produce a complete, hearing-ready appeal packet for the Miami-Dade Value Adjustment Board (VAB), with the property owner reviewing and signing before anything is filed.

---

## 1. Background: how a Miami-Dade appeal works

| Step | What happens | Timing (verify each year) |
|---|---|---|
| TRIM notice | Property Appraiser (PA) mails the *Notice of Proposed Property Taxes* showing just/market, assessed, and taxable value | Usually last week of August |
| Informal review | Owner can ask the PA to reconsider before filing; often resolves easy cases | Before the petition deadline |
| Petition | File Form **DR-486** with the VAB (online via the Clerk's AXIA portal, by mail, or in person). $15 per folio; $5 per additional folio for some joint condo/contiguous filings | 25 days after TRIM mailing — **Sept 18, 2026** for tax year 2026 |
| Evidence exchange | If the petitioner checks the box asking for the PA's evidence, the petitioner must give the PA its evidence ahead of the hearing (Fla. Stat. §194.011(4)); the PA then provides theirs | Petitioner: ≥15 days before hearing; PA: ≥7 days before hearing |
| Evidence upload | Evidence goes into the VAB AXIA system before the hearing | Third-party guidance says by 9:00 AM the day before. **Not yet confirmed with the Clerk** |
| Hearing | Special Magistrate hearing (in person or virtual); magistrate recommends, VAB adopts | Hearings run from fall into the following spring |
| Payment | At least 75% of the taxes must be paid by March 31 or the petition is denied (§194.014) | March 31 |

**Legal standard (what the packet must argue):**
- Just value = market value under the eight factors in §193.011, including the cost-of-sale adjustment in §193.011(8). The PA usually applies about 15% for this; the packet must check that it was applied.
- The PA's assessment is presumed correct. To win, the petitioner must show by a *preponderance of the evidence* that it is wrong, either because it exceeds just value or because the PA did not follow §193.011 (§194.301).
- Valid non-value claims are separate petition types: homestead or other exemption denials, portability, and Save Our Homes / 10% non-homestead cap errors. These use different DR-486 variants or checkboxes and different evidence.

> **Timing note:** today is 2026-10-14, so the 2026 filing window has closed. Right now the tool is useful in two ways: (a) building **evidence packets** for petitions already filed, whose hearings are coming up, and (b) getting ready for the **Aug–Sep 2027** filing window. The MVP should start with (a).

---

## 2. Product definition

### Inputs
- **Required:** folio number (13 digits) *or* site address, and the owner's contact and signature info.
- **Optional:** TRIM notice (PDF or photo, OCR'd), the owner's purchase closing statement, a recent private appraisal, repair estimates or contractor bids, photos of condition problems, insurance or flood information, and rent rolls or income statements for income property.

### Outputs: "the packet"
1. **Completed DR-486** (or the right variant), pre-filled and ready for signature, plus an agent authorization if someone files for the owner.
2. **Evidence package (PDF)** in a format magistrates are used to:
   - Cover sheet: folio, petition #, hearing date, requested value, and the one-line argument
   - Subject property summary: PA record, building characteristics, photos, map
   - **Comparable sales grid** (3–6 comps) with adjustments, and the indicated value
   - Cost-of-sale (§193.011(8)) check
   - Condition/defect exhibit (photos and repair bids → deduction)
   - Optional: income approach (for rentals and commercial), equity/uniformity exhibit, and assessment-history chart
   - Exhibit index with page numbers
3. **Hearing script / talking points**: a 2–3 minute oral summary, likely PA rebuttals, and the responses to them.
4. **Deadline calendar**: filing deadline, evidence-exchange date, upload date, hearing, and March 31 payment. This can be exported to ICS or Google Calendar.
5. **Go / No-go recommendation** before any of the above: estimated value reduction, tax savings (reduction × millage), the $15 fee, and confidence.

### Explicit non-goals (v1)
- Auto-submitting to AXIA without human review and signature.
- Representing the owner at the hearing.
- Commercial properties that need a certified appraisal (the tool flags these and refers them out).
- Counties other than Miami-Dade. The design should still make it easy to add other Florida counties later, because the DR-486 and Chapter 194 are statewide.

---

## 3. Agent architecture

A deterministic pipeline does the work, and an LLM agent handles the judgment and writing steps. All numbers come from code, never from model text.

```
 ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
 │ 1. Intake  │──▶│ 2. Data pull │──▶│ 3. Valuation  │──▶│ 4. Go/No-go  │
 │ folio/TRIM │   │ PA, DOR, GIS │   │ comps + adj.  │   │ savings calc │
 └────────────┘   └──────────────┘   └───────────────┘   └──────┬───────┘
                                                                 ▼
 ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
 │ 8. File /  │◀──│ 7. Human     │◀──│ 6. Assemble   │◀──│ 5. Narrative │
 │ calendar   │   │ review+sign  │   │ PDF + DR-486  │   │ + script     │
 └────────────┘   └──────────────┘   └───────────────┘   └──────────────┘
```

| Stage | Responsibility | Deterministic vs. LLM |
|---|---|---|
| 1. Intake | Normalize the folio or address. OCR the TRIM notice to pull just, assessed, and taxable values, millage, and mailing date | OCR + regex; LLM fallback for messy photos |
| 2. Data pull | Subject record, sales history, building data, exemptions, and neighborhood sales | Deterministic connectors (below) |
| 3. Valuation | Comp selection (distance, use code, size, age, sale date, qualified-sale flag), paired adjustments, reconciliation, cost-of-sale check, and a cap/exemption audit | Deterministic scoring and math. LLM only explains why each comp was chosen |
| 4. Go/No-go | Δ value × millage = savings, compared with fee and effort. Flags weak cases (e.g., assessment already below comps) | Deterministic |
| 5. Narrative | Argument summary, exhibit captions, hearing script, and rebuttal prep | LLM, using a template and grounded only in stage 3 output |
| 6. Assemble | Fill the DR-486 PDF fields and render the evidence PDF (HTML→PDF), maps, and charts | Deterministic |
| 7. Review | Owner or agent edits the requested value, removes comps, adds photos, and e-signs | UI |
| 8. File / calendar | Download the bundle, show guided AXIA upload steps, and create calendar reminders | Deterministic. Direct portal automation is a later decision (see §6) |

### Data sources
| Source | Use | Access |
|---|---|---|
| Miami-Dade Property Appraiser property search / public API | Subject characteristics, value history, exemptions, recent sales | Public web; check the terms of service and rate limits. Use bulk files if available |
| **FL DOR NAL + SDF files** (Property Tax Oversight data portal) | Countywide parcel attributes and the qualified sales file, with sale-qualification codes. **This is the backbone for comps** | Free CSV download; preliminary roll in July, final in October |
| Miami-Dade Open Data / GIS hub | Parcel polygons, neighborhoods, flood zones, and municipality (for millage) | ArcGIS REST / open data |
| TRIM notice (user-provided) | Proposed values, millage rates, and the mailing date, which sets the deadline | OCR |
| Miami-Dade Clerk VAB / AXIA | Deadlines, forms, petition status, and hearing dates | Public pages. Portal is account-based |
| Optional MLS / listing data | Better comp detail and condition | Licensed. Out of scope for v1 |

---

## 4. Valuation engine (core IP)

- **Comp universe:** SDF qualified sales (qualification codes for arm's-length deals) within the last ~18 months before Jan 1 of the tax year. Same DOR use code, within about 0.5–1 mi (widened as needed), similar living area (±25%), year built (±15 yrs), and lot size. For condos, prefer sales in the same building or complex.
- **Time adjustment:** monthly trend from neighborhood median $/sqft regression, adjusted to the Jan 1 valuation date.
- **Adjustments:** living area, lot, age, pool, waterfront, garage, bed/bath, and condition. Use paired-sales or regression coefficients by neighborhood, with sensible defaults when data is thin.
- **Reconciliation:** weighted toward the comps needing the smallest total adjustment. Report the range and the point estimate.
- **Audits:**
  - Just value vs. indicated market value × 0.85 (cost-of-sale check)
  - Year-over-year assessed value increase vs. the SOH cap (homestead, CPI ≤3%) or the 10% non-homestead cap
  - Exemption missing compared with the owner's attestation (homestead, senior, veteran)
  - Equity: subject $/sqft vs. assessed $/sqft of neighbors
- **Output:** a structured `ValuationResult` JSON that every downstream document must cite, so the narrative cannot make up a number.

---

## 5. MVP plan

| Phase | Scope | Est. effort |
|---|---|---|
| **0. Research spike** | Confirm the 2026/2027 DR-486 field map, Miami-Dade VAB local rules (evidence format, page limits, AXIA upload rules, exchange deadlines), and PA data-access terms. Collect 10–20 real magistrate decisions to see what wins | 1 week |
| **1. Evidence-packet MVP** (residential single-family and condo, already-filed petitions) | Folio in → comps → evidence PDF + hearing script + calendar. CLI or simple web form | 3–4 weeks |
| **2. Petition generation** | TRIM OCR, DR-486 auto-fill, go/no-go, e-sign, and filing instructions, ready for the Aug 2027 window | 2–3 weeks |
| **3. Scale** | Batch mode (agents and condo associations, many folios), exemption/portability petitions, income approach for small rentals, and other FL counties | Ongoing |

**Proposed stack:** Python (data and valuation: pandas/geopandas, DOR CSVs in DuckDB or Postgres+PostGIS), the Claude API for narrative and OCR fallback, WeasyPrint or Playwright for HTML→PDF, pypdf for DR-486 form fill, and a small web UI (Next.js or similar) with Supabase for accounts and storage.

**Success metrics:** % of packets needing no manual edits. Time from folio to packet (under 10 minutes). Win rate and average reduction on hearings, tracked by outcome. Owner-reported savings.

---

## 6. Risks & open questions

1. **Unauthorized practice of law / licensing.** Preparing your *own* petition is fine. Filing for others for pay requires being a proper agent (the DR-486 agent section and owner authorization). Only licensed appraisers can call valuation work an "appraisal." Packets should say "evidence of market value prepared by the owner" or "comparative market analysis." **Get a Florida attorney review before charging money.**
2. **Portal automation.** Scripting AXIA submissions may break its terms and is fragile. Default to guided manual upload. Revisit if the Clerk offers bulk or agent filing.
3. **Data access.** Check the PA website's scraping terms. DOR bulk files reduce this risk but lag by months, so recent sales may need PA lookups.
4. **Model hallucination.** The narrative layer may only reference fields from `ValuationResult`. Add a validation pass that every number in the PDF matches the source data.
5. **Downside risk to owners.** The VAB can't raise the value above the PA's figure in a petition hearing, but a weak case still costs the fee and time. The go/no-go gate should be conservative.
6. **Rule changes.** The 2026 DR-486 was in draft (07.15.26). Keep the form version, deadlines, and fees in per-tax-year config, not code.
7. **Open questions for the owner of this project:**
   - Who is the user: homeowners directly, tax agents and condo associations, or both? This decides the batch-vs-guided UX.
   - Business model: flat fee, contingency (% of savings), or free tool?
   - Should v1 include exemption and portability petitions, or value only?

---

## Sources
- [Miami-Dade Clerk — Value Adjustment Board](https://www.miamidadeclerk.gov/clerk/value-adjustment-board.page) (2026 deadline Sept 18; $15/folio fee)
- [Miami-Dade VAB AXIA portal (2026)](https://vabprod.miamidade.gov/axiaweb2026/)
- [FL DOR — DR-486 draft 07.15.26](https://floridarevenue.com/rules/pdf/DR-486%20Draft_07.15.26.pdf)
- [FL DOR — Download Assessment Roll and GIS Data (NAL/SDF/NAP)](https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx)
- [FL DOR — 2026 NAL/SDF/NAP User's Guide](https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/User%20Guides/2026%20Users%20guide%20and%20quick%20reference/2026_NAL_SDF_NAP_Users_Guide.pdf)
- [AppealDesk — Miami-Dade appeal guide](https://www.appealdesk.com/blog/miami-dade-county-property-tax-appeal) (third-party; evidence-upload timing unverified)
- Florida Statutes §§193.011, 194.011, 194.014, 194.301
