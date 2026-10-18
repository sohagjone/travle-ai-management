"""Single entry point for every download format.

    exports = build_all_exports(report)      # dict: key -> ExportFile
    exports["pdf"].data / .filename / .mime / .error

Each format is generated independently: if one fails (for example Word), the
others still work and the failed one carries a readable `error` message.
Nothing is written to disk; files live in memory as bytes.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .config import redact
from .report_data import FLIGHT_COLUMNS, HOTEL_COLUMNS, Column, clean_text, file_stem

log = logging.getLogger("travel_app")

MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "csv": "text/csv",
    "json": "application/json",
}


@dataclass
class ExportFile:
    key: str
    label: str
    filename: str
    mime: str
    data: Optional[bytes] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.data is not None and self.error is None


def csv_safe(value: Any) -> Any:
    """Stop spreadsheet formula injection: text starting with = + - @ is prefixed with a quote."""
    if isinstance(value, str):
        value = clean_text(value)
        if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + value
    return value


def _build_csv(columns: List[Column], rows: List[Dict[str, Any]]) -> bytes:
    """UTF-8 with BOM so Excel shows accents/symbols correctly; numbers stay plain numbers."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([c.header for c in columns])
    for row in rows:
        writer.writerow(["" if row.get(c.key) is None else csv_safe(row.get(c.key)) for c in columns])
    return buffer.getvalue().encode("utf-8-sig")


def build_flights_csv(report: Dict[str, Any]) -> bytes:
    return _build_csv(FLIGHT_COLUMNS, report["flights"])


def build_hotels_csv(report: Dict[str, Any]) -> bytes:
    # amenities_list/image_url are internal helpers, not CSV columns.
    return _build_csv(HOTEL_COLUMNS, report["hotels"])


def build_json(report: Dict[str, Any]) -> bytes:
    """Structured export. The email address and any secrets are never in `report`."""
    flights = [{k: v for k, v in row.items() if k != "top_pick"} | {"google_top_pick": row.get("top_pick") == "Yes"} for row in report["flights"]]
    hotels = [{k: v for k, v in row.items() if k not in ("amenities", "amenities_list")} | {"amenities": row.get("amenities_list", [])} for row in report["hotels"]]
    payload = {
        "schema_version": report["schema_version"],
        "generated_at": report["generated_at"],
        "search_request": report["request"],
        "flights": flights,
        "hotels": hotels,
        "recommendations": report["recommendations"],
        "cost_estimate": report["cost_estimate"],
        "sources": report["sources"],
        "notes": report["notes"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _safe_build(key: str, label: str, filename: str, builder: Callable[[], bytes]) -> ExportFile:
    try:
        return ExportFile(key, label, filename, MIME[filename.rsplit(".", 1)[-1]], data=builder())
    except Exception as exc:  # keep the app alive; show a helpful message
        log.exception("Export '%s' failed", key)
        return ExportFile(key, label, filename, MIME[filename.rsplit(".", 1)[-1]], error=f"{label} export failed: {redact(exc)}")


def build_all_exports(report: Dict[str, Any]) -> Dict[str, ExportFile]:
    # Imported here so a problem in one library cannot stop the whole app from starting.
    stem = file_stem(report)
    exports: Dict[str, ExportFile] = {}

    def pdf():
        from .pdf_generator import build_pdf
        return build_pdf(report)

    def xlsx():
        from .excel_generator import build_excel
        return build_excel(report)

    def docx():
        from .docx_generator import build_docx
        return build_docx(report)

    exports["pdf"] = _safe_build("pdf", "PDF report", f"{stem}.pdf", pdf)
    exports["xlsx"] = _safe_build("xlsx", "Excel workbook", f"{stem}.xlsx", xlsx)
    exports["flights_csv"] = _safe_build("flights_csv", "Flights CSV", f"{stem}_flights.csv", lambda: build_flights_csv(report))
    exports["hotels_csv"] = _safe_build("hotels_csv", "Hotels CSV", f"{stem}_hotels.csv", lambda: build_hotels_csv(report))
    exports["json"] = _safe_build("json", "JSON data", f"{stem}.json", lambda: build_json(report))
    exports["docx"] = _safe_build("docx", "Word report", f"{stem}.docx", docx)
    return exports
