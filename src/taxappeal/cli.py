"""Command-line entry point.

    taxappeal list-mock
    taxappeal generate examples/strong_case.json --out out/
    taxappeal serve                # web UI at http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .connectors import REGISTRY, build_connectors
from .connectors.mock import mock_folios
from .models import CaseInput
from .pipeline import generate_packet, write_outputs


def _generate(args: argparse.Namespace) -> int:
    case = CaseInput.model_validate(json.loads(Path(args.case).read_text()))
    choices = {kind: getattr(args, kind) for kind in REGISTRY}
    packet = generate_packet(case, build_connectors(**choices))
    out_dir = Path(args.out) / case.folio
    files = write_outputs(packet, out_dir, pdf=not args.no_pdf)

    d, v = packet.decision, packet.valuation
    print(f"{packet.property.address}  (folio {case.folio})")
    print(f"  Recommendation:      {d.recommendation.value.upper()}")
    print(f"  PA just value:       ${v.current_just_value:,}")
    print(f"  Requested just value:${v.requested_just_value:,}  (confidence: {v.confidence})")
    print(f"  Est. annual savings: ${d.estimated_annual_savings:,}")
    for r in d.reasons:
        print(f"   - {r}")
    print("  Files:")
    for path in files.values():
        print(f"    {path}")
    if not any(k.endswith("_pdf") for k in files) and not args.no_pdf:
        print("  (PDF skipped: Chromium not found; set CHROMIUM_PATH)")
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
    for kind, impls in REGISTRY.items():
        gen.add_argument(f"--{kind.replace('_', '-')}", dest=kind, default="mock", choices=sorted(impls),
                         help=f"{kind} connector (default: mock)")

    args = parser.parse_args(argv)
    if args.cmd == "list-mock":
        for folio, address in mock_folios():
            print(f"{folio}  {address}")
        return 0
    if args.cmd == "serve":
        from .web import serve

        serve(args.host, args.port)
        return 0
    return _generate(args)


if __name__ == "__main__":
    sys.exit(main())
