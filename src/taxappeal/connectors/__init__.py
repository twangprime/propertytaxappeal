"""Connector registry. Pick an implementation per connector by name, e.g.

    build_connectors(property_records="mock", sales="dor_sdf")

Register a new implementation by adding a factory to the matching dict below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .base import NarrativeWriter, PropertyRecordSource, SalesSource, TrimNoticeSource
from .mock import MockNarrativeWriter, MockPropertyRecords, MockSales, MockTrimNotices


@dataclass
class Connectors:
    property_records: PropertyRecordSource
    sales: SalesSource
    trim_notices: TrimNoticeSource
    narrative: NarrativeWriter

    def describe(self) -> dict[str, str]:
        return {
            "property_records": self.property_records.name,
            "sales": self.sales.name,
            "trim_notices": self.trim_notices.name,
            "narrative": self.narrative.name,
        }


REGISTRY: dict[str, dict[str, Callable[[], object]]] = {
    "property_records": {"mock": MockPropertyRecords},
    "sales": {"mock": MockSales},
    "trim_notices": {"mock": MockTrimNotices},
    "narrative": {"mock": MockNarrativeWriter},
}


def build_connectors(**choices: str) -> Connectors:
    unknown = set(choices) - set(REGISTRY)
    if unknown:
        raise ValueError(f"Unknown connector kind(s): {sorted(unknown)}")
    built = {}
    for kind, impls in REGISTRY.items():
        impl = choices.get(kind, "mock")
        if impl not in impls:
            raise ValueError(f"No '{impl}' implementation for {kind}; available: {sorted(impls)}")
        built[kind] = impls[impl]()
    return Connectors(**built)
