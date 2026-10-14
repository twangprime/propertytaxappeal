"""Domain models shared by connectors, the valuation engine and renderers.

Every number that ends up in a packet originates in one of these models, so the
narrative and rendering layers never invent figures.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class PropertyUse(str, Enum):
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"


class Building(BaseModel):
    use: PropertyUse
    living_sqft: int
    lot_sqft: int = 0  # 0 for condos
    year_built: int
    bedrooms: int | None = None  # not in the DOR roll; None = unknown
    bathrooms: float | None = None
    pool: bool | None = None
    waterfront: bool = False
    condition: int = Field(3, ge=1, le=5, description="1=poor, 3=average, 5=excellent")


class Location(BaseModel):
    lat: float | None = None  # None when no parcel coordinates are loaded
    lon: float | None = None
    neighborhood: str
    municipality: str
    market_area: str = ""

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lon is not None


class Assessment(BaseModel):
    tax_year: int
    just_value: int
    assessed_value: int
    taxable_value: int


class PropertyRecord(BaseModel):
    """What the Property Appraiser publishes about a parcel."""

    folio: str
    address: str
    building: Building
    location: Location
    homestead: bool
    last_sale_date: date | None = None  # a sale resets the assessment cap
    exemptions_total: int = 0
    assessments: list[Assessment] = Field(default_factory=list, description="Newest first")

    def assessment_for(self, tax_year: int) -> Assessment | None:
        return next((a for a in self.assessments if a.tax_year == tax_year), None)


class Sale(BaseModel):
    """One record from the DOR Sale Data File (SDF), joined to its parcel attributes."""

    folio: str
    address: str
    sale_date: date
    price: int
    qualified: bool = Field(description="Arm's-length per DOR qualification code")
    building: Building
    location: Location


class TrimNotice(BaseModel):
    """Values read from the Notice of Proposed Property Taxes."""

    folio: str
    tax_year: int
    mailing_date: date
    just_value: int
    assessed_value: int
    taxable_value: int
    prior_assessed_value: int | None = None  # None = unknown; cap check is skipped
    total_millage: float = Field(description="Combined proposed millage (mills per $1,000)")
    petition_deadline: date | None = Field(None, description="Deadline printed on the notice, if any")


class Owner(BaseModel):
    name: str
    mailing_address: str
    phone: str = ""
    email: str = ""


class RepairEstimate(BaseModel):
    description: str
    amount: int
    source: str = Field(description="Contractor name or 'owner estimate'")


class CaseInput(BaseModel):
    """Everything the homeowner tells us."""

    folio: str
    owner: Owner
    tax_year: int
    hearing_date: date | None = None
    petition_filed: bool = False
    repair_estimates: list[RepairEstimate] = Field(default_factory=list)
    recent_improvements: bool = Field(
        False, description="New construction/additions since last year (explains cap overages)"
    )
    trim_notice: TrimNotice | None = Field(
        None, description="Owner-confirmed TRIM values; takes precedence over the TRIM connector"
    )
    trim_notice_path: str | None = Field(None, description="Uploaded TRIM notice file for OCR")


# --- Valuation output -----------------------------------------------------------------


class Adjustment(BaseModel):
    factor: str
    amount: int
    explanation: str


class Comparable(BaseModel):
    sale: Sale
    distance_mi: float | None  # None when coordinates are unavailable
    months_before_valuation: float
    adjustments: list[Adjustment]
    adjusted_price: int
    gross_adjustment_pct: float
    net_adjustment_pct: float
    weight: float
    selection_reason: str


class AuditFinding(BaseModel):
    code: str
    severity: str  # "info" | "issue"
    message: str
    amount: int | None = None
    figures: dict[str, int] = Field(default_factory=dict, description="Source values cited in message")


class ValuationResult(BaseModel):
    folio: str
    tax_year: int
    valuation_date: date
    comps: list[Comparable]
    indicated_market_value: int
    repair_deduction: int
    adjusted_market_value: int
    cost_of_sale_pct: float
    requested_just_value: int
    current_just_value: int
    current_assessed_value: int
    current_taxable_value: int
    adjusted_price_low: int
    adjusted_price_high: int
    coefficient_of_variation: float
    audits: list[AuditFinding]
    confidence: str  # "high" | "medium" | "low"


class Recommendation(str, Enum):
    GO = "go"
    MAYBE = "maybe"
    NO_GO = "no_go"


class Decision(BaseModel):
    recommendation: Recommendation
    just_value_reduction: int
    new_assessed_value: int
    new_taxable_value: int
    taxable_reduction: int
    estimated_annual_savings: int
    filing_fee: int
    reasons: list[str]


class Deadline(BaseModel):
    name: str
    due: date
    description: str
    verified: bool = True


class Narrative(BaseModel):
    one_line_argument: str
    summary: str
    comp_explanations: dict[str, str]  # folio -> why it was chosen
    hearing_script: str
    rebuttals: list[tuple[str, str]]  # (likely PA argument, response)


class Packet(BaseModel):
    case: CaseInput
    property: PropertyRecord
    trim: TrimNotice
    valuation: ValuationResult
    decision: Decision
    deadlines: list[Deadline]
    narrative: Narrative
    petition_fields: dict[str, str]
    data_sources: dict[str, str]
    warnings: list[str] = Field(default_factory=list, description="Data issues the owner should review")
