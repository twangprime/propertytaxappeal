"""Command-line entry point.

    taxappeal list-mock
    taxappeal generate examples/strong_case.json --out out/
    taxappeal import-dor --nal NAL23F202601.csv --sdf SDF23F202601.csv [--coords points.csv]
    taxappeal generate case.json --property-records dor --sales dor --trim-notice notice.pdf
    taxappeal ocr notice.pdf       # print the values read from a TRIM notice
    taxappeal serve                # web UI at http://127.0.0.1:8000

Connector choices also come from TAXAPPEAL_CONNECTORS (e.g. "property_records=dor,sales=dor");
command-line flags win.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .connectors import REGISTRY, build_connectors, choices_from_env
from .connectors.mock import mock_folios
from .models import CaseInput
from .pipeline import generate_packet, normalize_folio, write_outputs


def _generate(args: argparse.Namespace) -> int:
    case = CaseInput.model_validate(json.loads(Path(args.case).read_text()))
    choices = choices_from_env()
    if args.trim_notice:
        case.trim_notice_path = str(Path(args.trim_notice).resolve())
        choices.setdefault("trim_notices", "ocr")
    choices.update({kind: getattr(args, kind) for kind in REGISTRY if getattr(args, kind)})
    packet = generate_packet(case, build_connectors(**choices))
    out_dir = Path(args.out) / normalize_folio(case.folio)
    files = write_outputs(packet, out_dir, pdf=not args.no_pdf)

    d, v = packet.decision, packet.valuation
    print(f"{packet.property.address}  (folio {packet.property.folio})")
    print(f"  Recommendation:      {d.recommendation.value.upper()}")
    print(f"  PA just value:       ${v.current_just_value:,}")
    print(f"  Requested just value:${v.requested_just_value:,}  (confidence: {v.confidence})")
    print(f"  Est. annual savings: ${d.estimated_annual_savings:,}")
    for r in d.reasons:
        print(f"   - {r}")
    for w in packet.warnings:
        print(f"  ! {w}")
    print("  Data sources: " + "; ".join(f"{k}={s}" for k, s in packet.data_sources.items()))
    print("  Files:")
    for path in files.values():
        print(f"    {path}")
    if not any(k.endswith("_pdf") for k in files) and not args.no_pdf:
        print("  (PDF skipped: Chromium not found; set CHROMIUM_PATH)")
    return 0


def _import_dor(args: argparse.Namespace) -> int:
    from .connectors.dor import import_dor

    print(f"Importing {args.nal} and {args.sdf} into {args.db} …")
    stats = import_dor(Path(args.nal), Path(args.sdf), Path(args.db),
                       Path(args.coords) if args.coords else None, args.county or None)
    print(f"  {stats['parcels']:,} parcels, {stats['sales']:,} sales, "
          f"{stats['parcels_with_coords']:,} parcels with coordinates")
    if not stats["parcels_with_coords"]:
        print("  No coordinates loaded: comparables will be chosen by DOR neighborhood code.")
    return 0


def _ocr(args: argparse.Namespace) -> int:
    from .connectors.ocr import ClaudeTrimReader

    extraction = ClaudeTrimReader().extract_file(Path(args.file))
    print(extraction.model_dump_json(indent=2))
    if extraction.missing():
        print(f"Missing: {', '.join(extraction.missing())}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taxappeal", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-mock", help="List folios available in the mock data")

    srv = sub.add_parser("serve", help="Run the local web UI")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)

    gen = sub.add_parser("generate", help="Generate an appeal packet from a case file")
    gen.add_argument("case", help="Path to a case JSON file (see examples/)")
    gen.add_argument("--out", default="out", help="Output directory (default: out/)")
    gen.add_argument("--no-pdf", action="store_true", help="Skip PDF rendering")
    gen.add_argument("--trim-notice", help="TRIM notice PDF/photo to read with OCR")
    for kind, impls in REGISTRY.items():
        gen.add_argument(f"--{kind.replace('_', '-')}", dest=kind, default=None, choices=sorted(impls),
                         help=f"{kind} connector (default: TAXAPPEAL_CONNECTORS or mock)")

    imp = sub.add_parser("import-dor", help="Index DOR NAL + SDF CSV files for the 'dor' connectors")
    imp.add_argument("--nal", required=True, help="NAL (real property roll) CSV")
    imp.add_argument("--sdf", required=True, help="SDF (sale data file) CSV")
    imp.add_argument("--coords", help="Optional CSV of folio, latitude, longitude (WGS84)")
    imp.add_argument("--db", default=None, help="SQLite index path (default: TAXAPPEAL_DOR_DB or data/dor.sqlite)")
    imp.add_argument("--county", default="23", help="DOR county number to keep (default 23, Miami-Dade; '' for all)")

    ocr = sub.add_parser("ocr", help="Read the values on a TRIM notice (needs an Anthropic API key)")
    ocr.add_argument("file", help="TRIM notice PDF or photo")

    args = parser.parse_args(argv)
    if args.cmd == "list-mock":
        for folio, address in mock_folios():
            print(f"{folio}  {address}")
        return 0
    if args.cmd == "serve":
        from .web import serve

        serve(args.host, args.port)
        return 0
    if args.cmd == "import-dor":
        if args.db is None:
            from .connectors.dor import DEFAULT_DB

            args.db = DEFAULT_DB
        return _import_dor(args)
    if args.cmd == "ocr":
        return _ocr(args)
    return _generate(args)


if __name__ == "__main__":
    sys.exit(main())
