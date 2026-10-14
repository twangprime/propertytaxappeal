"""Mock connectors backed by mock_data/mock_data.json (fictional data)."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from importlib import resources

from ..geo import distance_mi
from ..models import PropertyRecord, Sale, TrimNotice
from ..narrative import TemplateNarrativeWriter


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(resources.files("taxappeal").joinpath("mock_data/mock_data.json").read_text())


def mock_folios() -> list[tuple[str, str]]:
    return [(p["folio"], p["address"]) for p in _data()["properties"]]


class MockPropertyRecords:
    name = "mock (fictional Property Appraiser records)"

    def get_property(self, folio: str) -> PropertyRecord:
        for p in _data()["properties"]:
            if p["folio"] == folio:
                return PropertyRecord.model_validate(p)
        raise LookupError(f"Folio {folio} not found")


class MockSales:
    name = "mock (fictional DOR SDF sales)"

    def find_sales(
        self, near_lat: float, near_lon: float, radius_mi: float, start: date, end: date
    ) -> list[Sale]:
        sales = [Sale.model_validate(s) for s in _data()["sales"]]
        return [
            s
            for s in sales
            if start <= s.sale_date <= end
            and distance_mi(near_lat, near_lon, s.location.lat, s.location.lon) <= radius_mi
        ]


class MockTrimNotices:
    name = "mock (fictional TRIM notices)"

    def get_trim_notice(self, folio: str, tax_year: int) -> TrimNotice:
        for t in _data()["trim_notices"]:
            if t["folio"] == folio and t["tax_year"] == tax_year:
                return TrimNotice.model_validate(t)
        raise LookupError(f"No {tax_year} TRIM notice for folio {folio}")


class MockNarrativeWriter(TemplateNarrativeWriter):
    name = "mock (template narrative, no LLM)"
