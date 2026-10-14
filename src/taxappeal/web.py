"""Minimal local web UI (standard library only).

    taxappeal serve            # http://127.0.0.1:8000

Connectors come from TAXAPPEAL_CONNECTORS (default: all mock), e.g.
    TAXAPPEAL_CONNECTORS="property_records=dor,sales=dor" taxappeal serve
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, PackageLoader, StrictUndefined
from pydantic import ValidationError

from .connectors import Connectors, build_connectors, choices_from_env
from .connectors.mock import mock_folios
from .models import CaseInput, Packet, TrimNotice
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
MAX_BODY = 25 * 1024 * 1024
TRIM_FIELDS = ["trim_just_value", "trim_assessed_value", "trim_taxable_value", "trim_prior_assessed_value",
               "trim_total_millage", "trim_mailing_date", "trim_petition_deadline"]

Form = dict[str, list[str]]
Upload = tuple[str, str, bytes]  # filename, content type, data


def _one(form: Form, key: str) -> str:
    return form.get(key, [""])[0].strip()


def _money(value: str) -> int | None:
    value = value.replace(",", "").replace("$", "").strip()
    return int(float(value)) if value else None


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def parse_body(content_type: str, body: bytes) -> tuple[Form, dict[str, Upload]]:
    """Parse urlencoded or multipart form bodies (the cgi module is gone in Python 3.13)."""
    if not content_type.startswith("multipart/form-data"):
        return parse_qs(body.decode(), keep_blank_values=True), {}
    msg = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    form: Form = {}
    files: dict[str, Upload] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            if payload:
                files[name] = (filename, part.get_content_type(), payload)
        else:
            form.setdefault(name, []).append(payload.decode("utf-8", errors="replace"))
    return form, files


def trim_from_form(form: Form, folio: str, tax_year: int) -> TrimNotice | None:
    """Owner-entered or owner-confirmed TRIM values; None when the section was left blank."""
    if not any(_one(form, f) for f in TRIM_FIELDS):
        return None
    required = {"trim_just_value": "market (just) value", "trim_assessed_value": "assessed value",
                "trim_taxable_value": "taxable value", "trim_total_millage": "total millage"}
    missing = [label for key, label in required.items() if not _one(form, key)]
    if missing:
        raise ValueError(f"TRIM notice: please enter the {', '.join(missing)}.")
    return TrimNotice(
        folio=_one(form, "trim_folio") or folio,  # folio read from the notice, so a wrong notice is caught
        tax_year=tax_year,
        mailing_date=_date(_one(form, "trim_mailing_date")) or date(tax_year, 8, 24),
        just_value=_money(_one(form, "trim_just_value")),
        assessed_value=_money(_one(form, "trim_assessed_value")),
        taxable_value=_money(_one(form, "trim_taxable_value")),
        prior_assessed_value=_money(_one(form, "trim_prior_assessed_value")),
        total_millage=float(_one(form, "trim_total_millage")),
        petition_deadline=_date(_one(form, "trim_petition_deadline")),
    )


def case_from_form(form: Form) -> CaseInput:
    repairs = []
    for desc, amount, source in zip(form.get("repair_description", []), form.get("repair_amount", []),
                                    form.get("repair_source", [])):
        if desc.strip() or amount.strip():
            repairs.append({"description": desc.strip(), "source": source.strip() or "owner estimate",
                            "amount": _money(amount) or 0})
    folio = _one(form, "folio")
    tax_year = int(_one(form, "tax_year") or 2026)
    return CaseInput.model_validate({
        "folio": folio,
        "tax_year": tax_year,
        "owner": {
            "name": _one(form, "owner_name"),
            "mailing_address": _one(form, "mailing_address"),
            "phone": _one(form, "phone"),
            "email": _one(form, "email"),
        },
        "petition_filed": "petition_filed" in form,
        "hearing_date": _date(_one(form, "hearing_date")),
        "recent_improvements": "recent_improvements" in form,
        "repair_estimates": repairs,
        "trim_notice": trim_from_form(form, folio, tax_year),
    })


class App:
    def __init__(self, out_root: Path, connectors: Connectors | None = None, trim_reader=None):
        self.out_root = out_root
        self.connectors = connectors or build_connectors(**choices_from_env())
        self._trim_reader = trim_reader

    @property
    def mock_mode(self) -> bool:
        return "mock" in self.connectors.property_records.name

    def form_page(self, error: str = "", values: Form | None = None, notice: str = "",
                  ocr_notes: list[str] | None = None) -> str:
        values = values or {}
        return _env.get_template("app_form.html.j2").render(
            folios=mock_folios() if self.mock_mode else [], mock_mode=self.mock_mode,
            trim_required="mock" not in self.connectors.trim_notices.name,
            error=error, notice=notice, ocr_notes=ocr_notes or [],
            v=lambda k, default="": _one(values, k) or default,
            checked=lambda k: k in values,
            repairs=list(zip(values.get("repair_description", []), values.get("repair_amount", []),
                             values.get("repair_source", []))),
            sources=self.connectors.describe(),
        )

    def extract_trim(self, form: Form, files: dict[str, Upload]) -> str:
        """Read the uploaded TRIM notice and return the form pre-filled for the owner to confirm."""
        upload = files.get("trim_file")
        if not upload:
            return self.form_page("Choose your TRIM notice file first.", form)
        from .connectors.ocr import ClaudeTrimReader, media_type_for

        filename, ctype, data = upload
        try:
            reader = self._trim_reader or ClaudeTrimReader()
            extraction = reader.extract(data, media_type_for(filename, ctype))
        except Exception as e:  # any OCR failure falls back to manual entry
            reason = str(e)
            if "authentication" in reason.lower() or "api_key" in reason.lower():
                reason = "no Anthropic API key is configured on this server"
            return self.form_page(f"Couldn't read the notice automatically ({reason}). "
                                  f"Please type the values from your notice below.", form)
        if not extraction.is_trim_notice:
            return self.form_page("That file doesn't look like a TRIM notice. Please check the upload "
                                  "or type the values below.", form)
        filled = dict(form)
        field_map = {"trim_just_value": extraction.just_value, "trim_assessed_value": extraction.assessed_value,
                     "trim_taxable_value": extraction.taxable_value,
                     "trim_prior_assessed_value": extraction.prior_assessed_value,
                     "trim_total_millage": extraction.total_millage, "trim_mailing_date": extraction.mailing_date,
                     "trim_petition_deadline": extraction.petition_deadline}
        for key, val in field_map.items():
            filled[key] = ["" if val is None else str(val)]
        filled["trim_folio"] = [extraction.folio or ""]
        if extraction.folio and not _one(form, "folio"):
            filled["folio"] = [extraction.folio]
        if extraction.tax_year:
            filled["tax_year"] = [str(extraction.tax_year)]
        notice = "We read these values from your notice. Check each one against the notice before building."
        if extraction.missing():
            notice += f" Some values couldn't be read: {', '.join(extraction.missing())}."
        return self.form_page(notice=notice, values=filled, ocr_notes=extraction.notes)

    def generate(self, form: Form, pdf: bool) -> str:
        case = case_from_form(form)
        if case.trim_notice is None and "mock" not in self.connectors.trim_notices.name:
            raise ValueError("Upload your TRIM notice or type its values in section 2.")
        packet = generate_packet(case, self.connectors)
        safe = re.sub(r"[^0-9A-Za-z]", "", case.folio)[:20] or "case"
        run_id = f"{safe}-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(2)}"
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
            p=packet, v=packet.valuation, d=packet.decision, run_id=run_id, has_pdf=has_pdf,
            is_mock=any("mock" in s for s in packet.data_sources.values()))


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
            path = urlparse(self.path).path
            if path not in ("/generate", "/extract"):
                return self._send("Not found", HTTPStatus.NOT_FOUND, "text/plain")
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self._send("Upload too large (25 MB max)", HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "text/plain")
            form, files = parse_body(self.headers.get("Content-Type", ""), self.rfile.read(length))
            if path == "/extract":
                return self._send(app.extract_trim(form, files))
            try:
                run_id = app.generate(form, pdf="pdf" in form)
            except ValidationError as e:
                msg = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
                return self._send(app.form_page(f"Please check the form: {msg}", form), HTTPStatus.BAD_REQUEST)
            except (ValueError, LookupError, FileNotFoundError) as e:
                return self._send(app.form_page(str(e), form), HTTPStatus.BAD_REQUEST)
            self._send("", HTTPStatus.SEE_OTHER, headers={"Location": f"/result/{run_id}"})

        def log_message(self, fmt: str, *args) -> None:
            print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, out_root: Path = Path("out/web")) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    app = App(out_root)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Tax appeal UI running at http://{host}:{port}  (Ctrl+C to stop)")
    print("  Data sources: " + "; ".join(f"{k}={s}" for k, s in app.connectors.describe().items()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
