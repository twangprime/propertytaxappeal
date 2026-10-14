"""Connector interfaces. Each external dependency sits behind one of these protocols so the
mock implementations can be swapped for real ones independently."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ..models import (
    CaseInput,
    Decision,
    Narrative,
    PropertyRecord,
    Sale,
    TrimNotice,
    ValuationResult,
)


class PropertyRecordSource(Protocol):
    """Subject parcel data. Real impl: Miami-Dade Property Appraiser."""

    name: str

    def get_property(self, folio: str) -> PropertyRecord: ...


class SalesSource(Protocol):
    """Neighborhood sales. Real impl: FL DOR SDF joined to the NAL roll."""

    name: str

    def find_sales(
        self, subject: PropertyRecord, radius_mi: float, start: date, end: date
    ) -> list[Sale]:
        """Sales near the subject. Without coordinates, sales in the subject's neighborhood."""
        ...


class TrimNoticeSource(Protocol):
    """Values from the TRIM notice. Real impl: OCR of the owner's upload."""

    name: str

    def get_trim_notice(self, case: CaseInput) -> TrimNotice: ...


class NarrativeWriter(Protocol):
    """Prose for the packet. Real impl: Claude, grounded strictly in ValuationResult."""

    name: str

    def write(
        self,
        case: CaseInput,
        prop: PropertyRecord,
        valuation: ValuationResult,
        decision: Decision,
    ) -> Narrative: ...
