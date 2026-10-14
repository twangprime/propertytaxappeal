"""Minimal local web UI (standard library only).

    taxappeal serve            # http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, PackageLoader, StrictUndefined
from pydantic import ValidationError

from .connectors import build_connectors
from .connectors.mock import mock_folios
from .models import CaseInput, Packet
from .pipeline import generate_packet, write_outputs

_env = Environment(loader=PackageLoader("taxappeal", "templates"), autoescape=True,
                   undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
_env.filters["money"] = lambda v: f"${v:,.0f}"

# Only these generated files may be served back to the browser.
SERVABLE = {
    "evidence.html": "text/html; charset=utf-8",
    "owner_guide.html": "text/html; charset=utf-8",
    "evidence.pdf": "application/pdf",
    "owner_guide.pdf": "application/pdf",
    "deadlines.ics": "text/calendar; charset=utf-8",
    "dr486_worksheet.json": "application/json",
    "packet.json": "application/json",
}
RUN_ID = re.compile(r"^[0-9A-Za-z-]+$")


def _one(form: dict[str, list[str]], key: str) -> str:
    return form.get(key, [""])[0].strip()


def case_from_form(form: dict[str, list[str]]) -> CaseInput:
    repairs = []
    for desc, amount, source in zip(form.get("repair_description", []), form.get("repair_amount", []),
                                    form.get("repair_source", [])):
        if desc.strip() or amount.strip():
            repairs.append({"description": desc.strip(), "source": source.strip() or "owner estimate",
                            "amount": int(float(amount.replace(",", "").replace("$", "") or 0))})
    hearing = _one(form, "hearing_date")
    return CaseInput.model_validate({
        "folio": _one(form, "folio"),
        "tax_year": int(_one(form, "tax_year") or 2026),
        "owner": {
            "name": _one(form, "owner_name"),
            "mailing_address": _one(form, "mailing_address"),
            "phone": _one(form, "phone"),
            "email": _one(form, "email"),
        },
        "petition_filed": "petition_filed" in form,
        "hearing_date": date.fromisoformat(hearing) if hearing else None,
        "recent_improvements": "recent_improvements" in form,
        "repair_estimates": repairs,
    })


class App:
    def __init__(self, out_root: Path):
        self.out_root = out_root

    def form_page(self, error: str = "", values: dict[str, list[str]] | None = None) -> str:
        values = values or {}
        return _env.get_template("app_form.html.j2").render(
            folios=mock_folios(), error=error,
            v=lambda k, default="": _one(values, k) or default,
            checked=lambda k: k in values,
            repairs=list(zip(values.get("repair_description", []), values.get("repair_amount", []),
                             values.get("repair_source", []))),
        )

    def generate(self, form: dict[str, list[str]], pdf: bool) -> str:
        case = case_from_form(form)
        packet = generate_packet(case, build_connectors())
        run_id = f"{case.folio}-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(2)}"
        files = write_outputs(packet, self.out_root / run_id, pdf=pdf)
        (self.out_root / run_id / "meta.json").write_text(json.dumps({"pdf": "evidence_pdf" in files}))
        return run_id

    def result_page(self, run_id: str) -> str | None:
        run_dir = self.out_root / run_id
        if not RUN_ID.match(run_id) or not (run_dir / "packet.json").exists():
            return None
        packet = Packet.model_validate_json((run_dir / "packet.json").read_text())
        has_pdf = json.loads((run_dir / "meta.json").read_text()).get("pdf", False)
        return _env.get_template("app_result.html.j2").render(
            p=packet, v=packet.valuation, d=packet.decision, run_id=run_id, has_pdf=has_pdf)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes | str, status: int = 200, ctype: str = "text/html; charset=utf-8",
                  headers: dict[str, str] | None = None) -> None:
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, val in (headers or {}).items():
                self.send_header(k, val)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                return self._send(app.form_page())
            m = re.fullmatch(r"/result/([^/]+)", path)
            if m:
                page = app.result_page(m.group(1))
                return self._send(page) if page else self._send("Not found", HTTPStatus.NOT_FOUND, "text/plain")
            m = re.fullmatch(r"/files/([^/]+)/([^/]+)", path)
            if m and RUN_ID.match(m.group(1)) and m.group(2) in SERVABLE:
                f = app.out_root / m.group(1) / m.group(2)
                if f.exists():
                    download = m.group(2).endswith((".ics", ".json"))
                    return self._send(f.read_bytes(), ctype=SERVABLE[m.group(2)], headers={
                        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{m.group(2)}"'})
            self._send("Not found", HTTPStatus.NOT_FOUND, "text/plain")

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/generate":
                return self._send("Not found", HTTPStatus.NOT_FOUND, "text/plain")
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            try:
                run_id = app.generate(form, pdf="pdf" in form)
            except ValidationError as e:
                msg = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
                return self._send(app.form_page(f"Please check the form: {msg}", form), HTTPStatus.BAD_REQUEST)
            except (ValueError, LookupError) as e:
                return self._send(app.form_page(str(e), form), HTTPStatus.BAD_REQUEST)
            self._send("", HTTPStatus.SEE_OTHER, headers={"Location": f"/result/{run_id}"})

        def log_message(self, fmt: str, *args) -> None:
            print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, out_root: Path = Path("out/web")) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), make_handler(App(out_root)))
    print(f"Tax appeal UI running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
