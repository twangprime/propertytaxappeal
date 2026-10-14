# Data sources

What each connector reads, how fields map to the app's model, and what still needs checking against official documentation.

## FL DOR bulk files (`dor` connectors)

**Source:** FL Department of Revenue, Property Tax Oversight data portal. There is one NAL (real property roll) and one SDF (sale data file) per county, as CSV with field names in the header row. Miami-Dade's DOR county number is **23**. The preliminary roll comes out in July and the final roll in October.

**Not yet checked against the actual files.** This build environment could not reach floridarevenue.com. The field names below follow the DOR User's Guide naming. The importer validates headers and lists anything missing, and the expected names live in `NAL_FIELDS` / `SDF_FIELDS` in `src/taxappeal/connectors/dor.py`. Check them against the User's Guide for the roll year you download.

### NAL → property record

| App field | NAL field(s) | Notes |
|---|---|---|
| Folio | `PARCEL_ID` | Digits only; shown as `30-4019-001-0100` |
| Property type | `DOR_UC` | `001` single family, `004` condo. Other codes are rejected for the subject and skipped as comps |
| Just / assessed / taxable value | `JV`, `AV_NSD`, `TV_NSD` | Non-school values. School values differ when the additional homestead exemption applies |
| Homestead | `JV_HMSTD` > 0 | |
| Exemptions | `AV_NSD − TV_NSD` | |
| Living area, lot, year built | `TOT_LVG_AREA`, `LND_SQFOOT`, `ACT_YR_BLT` (falls back to `EFF_YR_BLT`) | Lot is set to 0 for condos |
| Neighborhood | `NBRHD_CD` (`MKT_AR` kept too) | Used for comps when there are no coordinates |
| Address | `PHY_ADDR1`, `PHY_CITY`, `PHY_ZIPCD` | |
| Last sale (cap reset check) | `SALE_YR1/2`, `SALE_MO1/2`, `SALE_PRC1/2` | Sales under $10,000 are ignored |
| Coordinates | **not in the NAL** | Optional `--coords` CSV |
| Bedrooms, bathrooms, pool | **not in the NAL** | Left unknown. No adjustments are made for them, and they are hidden in the packet |
| Condition | **not in the NAL** | Treated as average (3). Owner repair estimates carry condition |

### SDF → comparable sales

| App field | SDF field | Notes |
|---|---|---|
| Sale price | `SALE_PRC` | Must be at least $10,000 |
| Sale date | `SALE_YR`, `SALE_MO` | Month only, so the 15th is used |
| Arm's length | `QUAL_CD` | Qualified only if the code is in `TAXAPPEAL_QUALIFIED_CODES` (default `01`). **Check the qualified codes in the DOR guide for the sale year** |
| Improved vs vacant | `VI_CD` | Only `I` (improved) sales qualify |
| Multi-parcel sale | `MULTI_PAR_SAL` | Excluded when set |
| Building attributes | Joined from the NAL by `PARCEL_ID` | These are **current-roll** attributes, so a house remodeled after its sale shows the new size |

## TRIM notice (`ocr` connector)

The owner uploads a PDF or photo. Claude (`claude-opus-5-5`, structured JSON output) reads the folio, tax year, mailing date, petition deadline, this year's just, assessed and taxable values, last year's assessed value, and the total proposed millage.

- Where school and non-school values differ, it uses the non-school values and notes both.
- Anything it can't read comes back blank with a note. The owner must confirm or enter values before a packet is built.
- The folio read from the notice must match the property. Value differences from the roll are listed as warnings.
- If a petition deadline is printed on the notice, it overrides the configured deadline.

## Still placeholders

| Item | Where | Next step |
|---|---|---|
| Adjustment rates | `AdjustmentRates` in `valuation.py` | Derive per neighborhood by regression on SDF sales |
| 2026 Save Our Homes cap (3% ceiling) | `rules.py` | Use the published CPI-based rate |
| Evidence-upload deadline | `rules.py` | Confirm with the VAB clerk |
| DR-486 form version | `rules.py`, `petition.py` | Confirm the final 2026 form |
| Narrative | `narrative.py` | Claude writer behind the grounding check |
