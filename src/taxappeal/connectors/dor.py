"""Florida DOR bulk assessment-roll connector (NAL roll + Sale Data File).

The DOR publishes each county's roll as CSV files with field names in the header row:
  * NAL ("Name-Address-Legal"): one row per parcel, with values, building data and the two
    most recent sales.
  * SDF ("Sale Data File"): every sale recorded in the prior and current year.

The files are large (Miami-Dade's NAL is roughly a million rows), so ``import_dor`` loads the
columns we need into a local SQLite index once; the connectors then query that index.

The roll has no coordinates. Pass ``coords`` (a CSV of folio + WGS84 lat/lon, e.g. exported
from Miami-Dade's GIS property point layer) to enable distance-based comparable selection;
without it, comparables come from the subject's DOR neighborhood code.

Field names follow the DOR NAL/SDF User's Guide. They can change between roll years, so the
expected headers live in ``NAL_FIELDS`` / ``SDF_FIELDS`` and are validated at import time.
"""

from __future__ import annotations

import csv
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from ..geo import distance_mi
from ..models import Assessment, Building, Location, PropertyRecord, PropertyUse, Sale

DEFAULT_DB = Path(os.environ.get("TAXAPPEAL_DOR_DB", "data/dor.sqlite"))
MIAMI_DADE_CO_NO = "23"

# DOR land-use codes handled by the valuation engine.
USE_CODES = {1: PropertyUse.SINGLE_FAMILY, 4: PropertyUse.CONDO}

# Sale qualification codes treated as arm's-length. Verify against the DOR user guide for the
# roll year being imported; override with TAXAPPEAL_QUALIFIED_CODES="01,02".
DEFAULT_QUALIFIED_CODES = ("01",)
MIN_SALE_PRICE = 10_000  # nominal-consideration transfers ($10, $100) are not market sales

# our column -> DOR header. Optional fields may be absent.
NAL_FIELDS = {
    "co_no": "CO_NO", "folio": "PARCEL_ID", "asmnt_yr": "ASMNT_YR", "dor_uc": "DOR_UC",
    "jv": "JV", "av_nsd": "AV_NSD", "tv_nsd": "TV_NSD", "jv_hmstd": "JV_HMSTD",
    "lnd_sqfoot": "LND_SQFOOT", "tot_lvg_area": "TOT_LVG_AREA", "act_yr_blt": "ACT_YR_BLT",
    "eff_yr_blt": "EFF_YR_BLT", "nbrhd_cd": "NBRHD_CD", "mkt_ar": "MKT_AR",
    "phy_addr1": "PHY_ADDR1", "phy_city": "PHY_CITY", "phy_zipcd": "PHY_ZIPCD",
    "sale_prc1": "SALE_PRC1", "sale_yr1": "SALE_YR1", "sale_mo1": "SALE_MO1",
    "sale_prc2": "SALE_PRC2", "sale_yr2": "SALE_YR2", "sale_mo2": "SALE_MO2",
}
NAL_OPTIONAL = {"eff_yr_blt", "mkt_ar", "jv_hmstd", "sale_prc2", "sale_yr2", "sale_mo2"}
SDF_FIELDS = {
    "co_no": "CO_NO", "folio": "PARCEL_ID", "sale_prc": "SALE_PRC", "sale_yr": "SALE_YR",
    "sale_mo": "SALE_MO", "qual_cd": "QUAL_CD", "vi_cd": "VI_CD", "multi_par": "MULTI_PAR_SAL",
    "or_book": "OR_BOOK", "or_page": "OR_PAGE",
}
SDF_OPTIONAL = {"vi_cd", "multi_par", "or_book", "or_page"}
INT_COLUMNS = {"asmnt_yr", "dor_uc", "jv", "av_nsd", "tv_nsd", "jv_hmstd", "lnd_sqfoot",
               "tot_lvg_area", "act_yr_blt", "eff_yr_blt", "sale_prc1", "sale_yr1", "sale_mo1",
               "sale_prc2", "sale_yr2", "sale_mo2", "sale_prc", "sale_yr", "sale_mo"}

SCHEMA = """
CREATE TABLE parcels (
  folio TEXT PRIMARY KEY, co_no TEXT, asmnt_yr INT, dor_uc INT, jv INT, av_nsd INT, tv_nsd INT,
  jv_hmstd INT, lnd_sqfoot INT, tot_lvg_area INT, act_yr_blt INT, eff_yr_blt INT, nbrhd_cd TEXT,
  mkt_ar TEXT, phy_addr1 TEXT, phy_city TEXT, phy_zipcd TEXT, sale_prc1 INT, sale_yr1 INT,
  sale_mo1 INT, sale_prc2 INT, sale_yr2 INT, sale_mo2 INT, lat REAL, lon REAL);
CREATE TABLE sales (
  folio TEXT, co_no TEXT, sale_prc INT, sale_yr INT, sale_mo INT, qual_cd TEXT, vi_cd TEXT,
  multi_par TEXT, or_book TEXT, or_page TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""
INDEXES = """
CREATE INDEX parcels_nbrhd ON parcels(nbrhd_cd);
CREATE INDEX parcels_lat ON parcels(lat);
CREATE INDEX sales_folio ON sales(folio);
CREATE INDEX sales_date ON sales(sale_yr, sale_mo);
"""


def normalize_folio(folio: str) -> str:
    return "".join(ch for ch in str(folio) if ch.isdigit())


def format_folio(folio: str) -> str:
    """Miami-Dade style 30-4019-001-0100 for 13-digit folios; others unchanged."""
    d = normalize_folio(folio)
    return f"{d[:2]}-{d[2:6]}-{d[6:9]}-{d[9:]}" if len(d) == 13 else folio


def _to_int(value: str) -> int | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _resolve_headers(header: list[str], fields: dict[str, str], optional: set[str], label: str) -> dict[str, int]:
    """Map our column names to CSV column indexes, failing loudly on missing required headers."""
    index = {h.strip().upper(): i for i, h in enumerate(header)}
    resolved, missing = {}, []
    for ours, theirs in fields.items():
        if theirs in index:
            resolved[ours] = index[theirs]
        elif ours not in optional:
            missing.append(theirs)
    if missing:
        raise ValueError(
            f"{label} file is missing expected column(s) {missing}. The header has: "
            f"{', '.join(header[:12])}{'…' if len(header) > 12 else ''}. If the DOR renamed fields for "
            f"this roll year, update {label}_FIELDS in connectors/dor.py."
        )
    return resolved


def _rows(path: Path, fields: dict[str, str], optional: set[str], label: str, county: str | None):
    csv.field_size_limit(sys.maxsize)
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        cols = _resolve_headers(next(reader), fields, optional, label)
        for raw in reader:
            row = {k: (raw[i] if i < len(raw) else "") for k, i in cols.items()}
            if county and normalize_folio(row.get("co_no", "")).lstrip("0") != county.lstrip("0"):
                continue
            row["folio"] = normalize_folio(row["folio"])
            for k in INT_COLUMNS & row.keys():
                row[k] = _to_int(row[k])
            yield row


def _read_coords(path: Path) -> dict[str, tuple[float, float]]:
    """Folio -> (lat, lon) from a CSV with a folio column and latitude/longitude columns."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        names = {n.strip().upper(): n for n in reader.fieldnames or []}
        pick = lambda *opts: next((names[o] for o in opts if o in names), None)  # noqa: E731
        folio_col = pick("FOLIO", "PARCEL_ID", "PARCELID")
        lat_col = pick("LAT", "LATITUDE", "Y")
        lon_col = pick("LON", "LONG", "LONGITUDE", "X")
        if not (folio_col and lat_col and lon_col):
            raise ValueError(f"Coordinates file needs folio, latitude and longitude columns; found {reader.fieldnames}")
        coords = {}
        for row in reader:
            try:
                lat, lon = float(row[lat_col]), float(row[lon_col])
            except (TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(
                    f"Coordinates look projected (e.g. State Plane feet), not latitude/longitude: "
                    f"{lat}, {lon}. Export the layer in WGS84 (EPSG:4326)."
                )
            coords[normalize_folio(row[folio_col])] = (lat, lon)
        return coords


def import_dor(nal: Path, sdf: Path, db: Path = DEFAULT_DB, coords: Path | None = None,
               county: str | None = MIAMI_DADE_CO_NO) -> dict[str, int]:
    """Build the SQLite index from DOR NAL + SDF CSV files. Replaces any existing index."""
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    geo = _read_coords(coords) if coords else {}

    cols = list(NAL_FIELDS)
    placeholders = ",".join("?" * (len(cols) + 2))
    n_parcels = n_geo = 0
    batch = []
    for row in _rows(nal, NAL_FIELDS, NAL_OPTIONAL, "NAL", county):
        lat, lon = geo.get(row["folio"], (None, None))
        n_geo += lat is not None
        batch.append([row.get(c) for c in cols] + [lat, lon])
        if len(batch) >= 5000:
            con.executemany(f"INSERT OR REPLACE INTO parcels ({','.join(cols)},lat,lon) VALUES ({placeholders})", batch)
            n_parcels += len(batch)
            batch = []
    con.executemany(f"INSERT OR REPLACE INTO parcels ({','.join(cols)},lat,lon) VALUES ({placeholders})", batch)
    n_parcels += len(batch)

    scols = list(SDF_FIELDS)
    n_sales = 0
    batch = []
    for row in _rows(sdf, SDF_FIELDS, SDF_OPTIONAL, "SDF", county):
        batch.append([row.get(c) for c in scols])
        if len(batch) >= 5000:
            con.executemany(f"INSERT INTO sales ({','.join(scols)}) VALUES ({','.join('?' * len(scols))})", batch)
            n_sales += len(batch)
            batch = []
    con.executemany(f"INSERT INTO sales ({','.join(scols)}) VALUES ({','.join('?' * len(scols))})", batch)
    n_sales += len(batch)

    if not n_parcels:
        con.close()
        tmp.unlink()
        raise ValueError(f"No NAL rows matched county {county}. Check the file or pass county=None.")
    con.executescript(INDEXES)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("nal_file", nal.name), ("sdf_file", sdf.name), ("county", county or "all"),
        ("imported_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("has_coords", str(bool(n_geo))),
    ])
    con.commit()
    con.close()
    os.replace(tmp, db)
    return {"parcels": n_parcels, "sales": n_sales, "parcels_with_coords": n_geo}


def _connect(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise FileNotFoundError(
            f"DOR index {db} not found. Build it with: taxappeal import-dor --nal NAL.csv --sdf SDF.csv"
        )
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _sale_date(year: int | None, month: int | None) -> date | None:
    # The roll records sale month only; use mid-month.
    if not year or not month or not 1 <= month <= 12:
        return None
    return date(year, month, 15)


def _building(row: sqlite3.Row) -> Building | None:
    use = USE_CODES.get(row["dor_uc"])
    if use is None or not row["tot_lvg_area"]:
        return None
    year = row["act_yr_blt"] or row["eff_yr_blt"]
    if not year:
        return None
    return Building(
        use=use,
        living_sqft=row["tot_lvg_area"],
        lot_sqft=0 if use == PropertyUse.CONDO else (row["lnd_sqfoot"] or 0),
        year_built=year,
    )


def _location(row: sqlite3.Row) -> Location:
    return Location(lat=row["lat"], lon=row["lon"], neighborhood=row["nbrhd_cd"] or "",
                    municipality=(row["phy_city"] or "").title(), market_area=row["mkt_ar"] or "")


def _address(row: sqlite3.Row) -> str:
    street, city, zipcode = ((row[k] or "").strip() for k in ("phy_addr1", "phy_city", "phy_zipcd"))
    tail = " ".join(filter(None, ["FL", zipcode]))
    return ", ".join(filter(None, [street, city, tail])) or "(no situs address)"


class DorPropertyRecords:
    name = "FL DOR NAL assessment roll"

    def __init__(self, db: Path | None = None):
        self.con = _connect(db or DEFAULT_DB)

    def get_property(self, folio: str) -> PropertyRecord:
        row = self.con.execute("SELECT * FROM parcels WHERE folio = ?", (normalize_folio(folio),)).fetchone()
        if row is None:
            raise LookupError(f"Folio {folio} not found in the DOR roll")
        building = _building(row)
        if building is None:
            raise ValueError(
                f"Folio {folio} has DOR use code {row['dor_uc']:03d}, or is missing living area or "
                f"year built. Only single-family homes (001) and condos (004) are supported."
            )
        sales = [(_sale_date(row[f"sale_yr{i}"], row[f"sale_mo{i}"]), row[f"sale_prc{i}"]) for i in (1, 2)]
        last_sale = max((d for d, p in sales if d and (p or 0) >= MIN_SALE_PRICE), default=None)
        return PropertyRecord(
            folio=format_folio(row["folio"]),
            address=_address(row),
            building=building,
            location=_location(row),
            homestead=(row["jv_hmstd"] or 0) > 0,
            last_sale_date=last_sale,
            exemptions_total=max(0, (row["av_nsd"] or 0) - (row["tv_nsd"] or 0)),
            assessments=[Assessment(tax_year=row["asmnt_yr"], just_value=row["jv"] or 0,
                                    assessed_value=row["av_nsd"] or 0, taxable_value=row["tv_nsd"] or 0)],
        )


class DorSales:
    name = "FL DOR Sale Data File (SDF)"

    def __init__(self, db: Path | None = None, qualified_codes: tuple[str, ...] | None = None):
        self.con = _connect(db or DEFAULT_DB)
        env = os.environ.get("TAXAPPEAL_QUALIFIED_CODES")
        codes = qualified_codes or (tuple(c.strip() for c in env.split(",")) if env else DEFAULT_QUALIFIED_CODES)
        self.qualified_codes = {c.zfill(2) for c in codes}

    def find_sales(self, subject: PropertyRecord, radius_mi: float, start: date, end: date) -> list[Sale]:
        loc = subject.location
        where = ["s.sale_yr BETWEEN ? AND ?", "s.sale_prc >= ?"]
        params: list = [start.year, end.year, MIN_SALE_PRICE]
        if loc.has_coords:
            dlat = radius_mi / 69.0
            dlon = radius_mi / (69.0 * math.cos(math.radians(loc.lat)))
            where += ["p.lat BETWEEN ? AND ?", "p.lon BETWEEN ? AND ?"]
            params += [loc.lat - dlat, loc.lat + dlat, loc.lon - dlon, loc.lon + dlon]
        else:
            where.append("p.nbrhd_cd = ?")
            params.append(loc.neighborhood)
        rows = self.con.execute(
            f"SELECT s.*, p.* , s.folio AS sale_folio FROM sales s JOIN parcels p ON p.folio = s.folio "
            f"WHERE {' AND '.join(where)}", params,
        ).fetchall()

        sales = []
        for row in rows:
            sale_date = _sale_date(row["sale_yr"], row["sale_mo"])
            building = _building(row)
            if sale_date is None or building is None or not start <= sale_date <= end:
                continue
            multi = (row["multi_par"] or "").strip().upper()
            location = _location(row)
            if loc.has_coords and location.has_coords and \
                    distance_mi(loc.lat, loc.lon, location.lat, location.lon) > radius_mi:
                continue
            sales.append(Sale(
                folio=format_folio(row["sale_folio"]),
                address=_address(row),
                sale_date=sale_date,
                price=row["sale_prc"],
                qualified=(row["qual_cd"] or "").strip().zfill(2) in self.qualified_codes
                and multi in ("", "N", "0")
                and (row["vi_cd"] or "I").strip().upper() == "I",
                building=building,
                location=location,
            ))
        return sales
