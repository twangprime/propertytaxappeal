"""HTML rendering (Jinja) and optional PDF conversion via headless Chromium."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from .models import Packet

ADJUSTMENT_FACTORS = ["Market conditions", "Living area", "Lot size", "Year built", "Pool",
                      "Bathrooms", "Condition"]

_env = Environment(
    loader=PackageLoader("taxappeal", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["money"] = lambda v: f"${v:,.0f}" if v is not None else ""
_env.filters["signed_money"] = lambda v: (f"+${v:,.0f}" if v > 0 else f"-${-v:,.0f}") if v else "—"
_env.filters["pct"] = lambda v, digits=0: f"{v * 100:.{digits}f}%"


def _map_points(packet: Packet, size: int = 320, pad: int = 28) -> list[dict]:
    """Subject + comps projected into an SVG box, for a simple location exhibit."""
    pts = [("S", packet.property.location.lat, packet.property.location.lon)]
    pts += [(str(i + 1), c.sale.location.lat, c.sale.location.lon)
            for i, c in enumerate(packet.valuation.comps)]
    lats, lons = [p[1] for p in pts], [p[2] for p in pts]
    clat, clon = (max(lats) + min(lats)) / 2, (max(lons) + min(lons)) / 2
    lon_factor = math.cos(math.radians(clat))  # a degree of longitude is shorter than one of latitude
    lons = [lon * lon_factor for lon in lons]
    clon *= lon_factor
    span = max(max(lats) - min(lats), max(lons) - min(lons), 0.005)
    scale = (size - 2 * pad) / span
    return [
        {"label": label, "x": round(size / 2 + (lon - clon) * scale, 1),
         "y": round(size / 2 - (lat - clat) * scale, 1)}
        for (label, lat, _), lon in zip(pts, lons)
    ]


def _context(packet: Packet) -> dict:
    return {
        "p": packet,
        "v": packet.valuation,
        "factors": [f for f in ADJUSTMENT_FACTORS
                    if any(a.factor == f for c in packet.valuation.comps for a in c.adjustments)],
        "map_points": _map_points(packet),
        "is_mock": any("mock" in s for s in packet.data_sources.values()),
    }


def render_evidence_html(packet: Packet) -> str:
    return _env.get_template("evidence.html.j2").render(**_context(packet))


def render_owner_guide_html(packet: Packet) -> str:
    return _env.get_template("owner_guide.html.j2").render(**_context(packet))


def find_chromium() -> str | None:
    candidates = [os.environ.get("CHROMIUM_PATH"), shutil.which("chromium"),
                  shutil.which("chromium-browser"), shutil.which("google-chrome"),
                  "/opt/pw-browsers/chromium"]
    return next((c for c in candidates if c and Path(c).exists()), None)


def render_pdf(html_path: Path, pdf_path: Path) -> Path | None:
    """Print HTML to PDF with headless Chromium. Returns None if Chromium isn't available."""
    chromium = find_chromium()
    if not chromium:
        return None
    subprocess.run(
        [chromium, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
        check=True, capture_output=True, timeout=120,
    )
    return pdf_path if pdf_path.exists() else None
