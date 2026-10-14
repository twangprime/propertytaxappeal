"""Connector registry. Pick an implementation per connector by name, e.g.

    build_connectors(property_records="dor", sales="dor", trim_notices="ocr")  # ocr = local, no API key

or set TAXAPPEAL_CONNECTORS="property_records=dor,sales=dor,trim_notices=ocr".

Register a new implementation by adding a factory to the matching dict below.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
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


def _dor_records():
    from .dor import DorPropertyRecords

    return DorPropertyRecords()


def _dor_sales():
    from .dor import DorSales

    return DorSales()


def _claude_trim():
    from .ocr import ClaudeTrimReader, OcrTrimNotices

    return OcrTrimNotices(reader_factory=ClaudeTrimReader, label="Claude")


def _local_trim():
    from .local_ocr import LocalTrimReader
    from .ocr import OcrTrimNotices

    return OcrTrimNotices(reader_factory=LocalTrimReader, label=LocalTrimReader.label)


REGISTRY: dict[str, dict[str, Callable[[], object]]] = {
    "property_records": {"mock": MockPropertyRecords, "dor": _dor_records},
    "sales": {"mock": MockSales, "dor": _dor_sales},
    "trim_notices": {"mock": MockTrimNotices, "ocr": _local_trim, "claude": _claude_trim},
    "narrative": {"mock": MockNarrativeWriter, "template": MockNarrativeWriter},
}


def choices_from_env(env: str | None = None) -> dict[str, str]:
    """Parse TAXAPPEAL_CONNECTORS, e.g. "property_records=dor,sales=dor"."""
    raw = os.environ.get("TAXAPPEAL_CONNECTORS", "") if env is None else env
    choices = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        kind, _, impl = item.partition("=")
        if not impl:
            raise ValueError(f"Bad TAXAPPEAL_CONNECTORS entry {item!r}; expected kind=implementation")
        choices[kind.strip()] = impl.strip()
    return choices


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
