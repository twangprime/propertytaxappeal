"""Write DOR-format NAL/SDF CSVs (fictional data derived from the mock dataset) for tests and demos."""

from __future__ import annotations

import csv
import json
from importlib import resources
from pathlib import Path

USE = {"single_family": "0001", "condo": "0004"}
NAL_HEADER = ["CO_NO", "PARCEL_ID", "FILE_T", "ASMNT_YR", "DOR_UC", "PA_UC", "JV", "AV_SD", "AV_NSD",
              "TV_SD", "TV_NSD", "JV_HMSTD", "LND_SQFOOT", "IMP_QUAL", "EFF_YR_BLT", "ACT_YR_BLT",
              "TOT_LVG_AREA", "NO_BULDNG", "QUAL_CD1", "SALE_PRC1", "SALE_YR1", "SALE_MO1",
              "QUAL_CD2", "SALE_PRC2", "SALE_YR2", "SALE_MO2", "OWN_NAME", "MKT_AR", "NBRHD_CD",
              "CENSUS_BK", "PHY_ADDR1", "PHY_ADDR2", "PHY_CITY", "PHY_ZIPCD"]
SDF_HEADER = ["CO_NO", "PARCEL_ID", "ASMNT_YR", "DOR_UC", "NBRHD_CD", "MKT_AR", "CENSUS_BK", "SALE_ID_CD",
              "SAL_CHG_CD", "VI_CD", "OR_BOOK", "OR_PAGE", "CLERK_NO", "QUAL_CD", "SALE_YR", "SALE_MO",
              "SALE_PRC", "MULTI_PAR_SAL", "RS_ID", "MP_ID"]


def digits(folio: str) -> str:
    return folio.replace("-", "")


def write_dor_files(out: Path, with_coords: bool = True) -> dict[str, Path]:
    data = json.loads(resources.files("taxappeal").joinpath("mock_data/mock_data.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    paths = {"nal": out / "NAL23F202601.csv", "sdf": out / "SDF23F202601.csv", "coords": out / "parcel_points.csv"}
    nbrhd = {}

    with open(paths["nal"], "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(NAL_HEADER)
        parcels = [(p, p["assessments"][0]) for p in data["properties"]]
        parcels += [(s, None) for s in data["sales"]]
        for i, (p, a) in enumerate(parcels):
            b, loc = p["building"], p["location"]
            code = nbrhd.setdefault(loc["neighborhood"], str(1100 + len(nbrhd)))
            if a is None:  # a sold parcel: synthesize current values from its sale
                jv = int(p["price"] * 0.85)
                a = {"tax_year": 2026, "just_value": jv, "assessed_value": jv, "taxable_value": jv}
            homestead = p.get("homestead", False)
            sale_yr, sale_mo = (p.get("last_sale_date") or p.get("sale_date") or "    -  ").split("-")[:2]
            street, _, rest = p["address"].replace(" (MOCK)", "").partition(", ")
            w.writerow([
                "23", digits(p["folio"]), "R", a["tax_year"], USE[b["use"]], "0101", a["just_value"],
                a["assessed_value"], a["assessed_value"], a["taxable_value"], a["taxable_value"],
                a["just_value"] if homestead else 0, b["lot_sqft"], "3", b["year_built"], b["year_built"],
                b["living_sqft"], 1, "01", p.get("price", 0) if "price" in p else 450000,
                sale_yr.strip(), sale_mo.strip(), "", "", "", "", "OWNER NAME WITHHELD", "07", code,
                f"1201{i:05d}", street.upper(), "", "MIAMI", "33155",
            ])

    with open(paths["sdf"], "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SDF_HEADER)
        for i, s in enumerate(data["sales"]):
            yr, mo, _ = s["sale_date"].split("-")
            w.writerow(["23", digits(s["folio"]), 2026, USE[s["building"]["use"]],
                        nbrhd[s["location"]["neighborhood"]], "07", "", f"S{i}", "", "I", "33000", str(100 + i),
                        "", "01" if s["qualified"] else "11", yr, mo, s["price"], "", "", ""])
        first = data["sales"][0]
        # Noise: a $100 quit-claim and a vacant-land sale, both of which must be ignored.
        w.writerow(["23", digits(first["folio"]), 2026, "0001", nbrhd[first["location"]["neighborhood"]], "07",
                    "", "X1", "", "I", "33001", "1", "", "01", "2025", "06", 100, "", "", ""])
        w.writerow(["23", digits(first["folio"]), 2026, "0001", nbrhd[first["location"]["neighborhood"]], "07",
                    "", "X2", "", "V", "33001", "2", "", "01", "2025", "07", 950000, "", "", ""])

    if with_coords:
        with open(paths["coords"], "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["FOLIO", "LAT", "LON"])
            for p in data["properties"] + data["sales"]:
                w.writerow([digits(p["folio"]), p["location"]["lat"], p["location"]["lon"]])
    return paths


if __name__ == "__main__":
    import sys

    for name, path in write_dor_files(Path(sys.argv[1] if len(sys.argv) > 1 else "examples/dor_sample")).items():
        print(name, path)
