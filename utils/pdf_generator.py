"""PDF report built with ReportLab (pure Python, works on Streamlit Cloud).

Unicode: we bundle the DejaVu Sans font (assets/fonts). Characters the font does
not contain (for example Chinese/Japanese) are replaced with '?' instead of
showing broken boxes. If the font files are missing we fall back to Helvetica.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .report_data import (
    FLIGHT_COLUMNS,
    HOTEL_COLUMNS,
    clean_text,
    display_value,
    fmt_money,
    safe_http_url,
)

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
BLUE = colors.HexColor("#1F4E79")
LIGHT = colors.HexColor("#EAF1F8")
GRID = colors.HexColor("#C8D3DE")

_font_cache: Dict[str, Any] = {}


def _register_fonts() -> Dict[str, Any]:
    if _font_cache:
        return _font_cache
    regular, bold = FONT_DIR / "DejaVuSans.ttf", FONT_DIR / "DejaVuSans-Bold.ttf"
    if regular.exists() and bold.exists():
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", str(regular)))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold)))
            pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu", boldItalic="DejaVu-Bold")
            font = pdfmetrics.getFont("DejaVu")
            _font_cache.update(
                regular="DejaVu", bold="DejaVu-Bold", glyphs=set(font.face.charToGlyph.keys())
            )
            return _font_cache
        except Exception:
            pass
    _font_cache.update(regular="Helvetica", bold="Helvetica-Bold", glyphs=None)
    return _font_cache


def _text(value: Any) -> str:
    """Clean, glyph-safe, XML-escaped text for a Paragraph."""
    fonts = _register_fonts()
    cleaned = clean_text(value)
    glyphs = fonts["glyphs"]
    if glyphs is not None:
        cleaned = "".join(ch if (ord(ch) in glyphs or ch in "\n\t ") else "?" for ch in cleaned)  # charToGlyph keys are code points
    else:
        cleaned = cleaned.encode("latin-1", "replace").decode("latin-1")
    return escape(cleaned)


def _link(url: Any, label: str = "Open link") -> str:
    safe = safe_http_url(url)
    if not safe:
        return "n/a"
    return f'<link href="{escape(safe, {chr(34): "&quot;"})}" color="#0563C1"><u>{escape(label)}</u></link>'


class _NumberedCanvas(canvas.Canvas):
    """Adds 'Page X of Y' and a footer disclaimer to every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages: List[dict] = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int):
        fonts = _register_fonts()
        self.setFont(fonts["regular"], 7.5)
        self.setFillColor(colors.grey)
        self.drawString(1.5 * cm, 0.9 * cm, "Search results only - not a booking. Verify prices before booking.")
        self.drawRightString(A4[0] - 1.5 * cm, 0.9 * cm, f"Page {self._pageNumber} of {total}")


def _styles() -> Dict[str, ParagraphStyle]:
    f = _register_fonts()
    base = ParagraphStyle("base", fontName=f["regular"], fontSize=9, leading=12, alignment=TA_LEFT)
    return {
        "base": base,
        "title": ParagraphStyle("title", parent=base, fontName=f["bold"], fontSize=20, leading=24, textColor=BLUE, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName=f["bold"], fontSize=13, leading=16, textColor=BLUE, spaceBefore=12, spaceAfter=6),
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5),
        "cell": ParagraphStyle("cell", parent=base, fontSize=7.5, leading=9.5),
        "head": ParagraphStyle("head", parent=base, fontName=f["bold"], fontSize=7.5, leading=9.5, textColor=colors.white),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=10, bulletIndent=0, spaceAfter=2),
    }


def _table(data: List[List[Any]], col_widths: List[float], header: bool = True) -> Table:
    table = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BLUE)]
        style += [("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT])]
    table.setStyle(TableStyle(style))
    return table


def build_pdf(report: Dict[str, Any]) -> bytes:
    st = _styles()
    req = report["request"]
    currency = req.get("currency") or "USD"
    story: List[Any] = []
    usable_width = A4[0] - 3 * cm

    # ---- Title
    story.append(Paragraph(_text(report["title"]), st["title"]))
    route = f"{req.get('origin')} to {req.get('destination')}"
    story.append(Paragraph(_text(f"{route} | {req.get('departure_date')} - {req.get('return_date')}"), st["base"]))
    story.append(Paragraph(_text(f"Generated {report['generated_at_display']}"), st["small"]))

    # ---- Search criteria
    story.append(Paragraph("Search criteria", st["h2"]))
    travellers = f"{req.get('adults')} adult(s), {req.get('children')} child(ren)"
    if req.get("children_ages"):
        travellers += f" (ages {', '.join(str(a) for a in req['children_ages'])})"
    criteria = [
        ("Origin", f"{req.get('origin')} ({req['origin_city']})" if req.get("origin_city") else req.get("origin")),
        ("Destination", f"{req.get('destination')} ({req['destination_city']})" if req.get("destination_city") else req.get("destination")),
        ("Hotel search city", req.get("hotel_search_city") or "n/a"),
        ("Departure date", req.get("departure_date")),
        ("Return date", req.get("return_date")),
        ("Nights", req.get("nights") if req.get("nights") is not None else "n/a"),
        ("Travellers", travellers),
        ("Rooms", req.get("rooms")),
        ("Flight stops filter", req.get("flight_stops_filter")),
        ("Currency", currency),
    ]
    rows = [[Paragraph(f"<b>{_text(k)}</b>", st["cell"]), Paragraph(_text(v), st["cell"])] for k, v in criteria]
    story.append(_table(rows, [4.5 * cm, usable_width - 4.5 * cm], header=False))

    # ---- Recommendations
    recs = report["recommendations"]
    story.append(Paragraph("Recommendations", st["h2"]))
    story.append(Paragraph(_text(recs.get("source_label") or ""), st["small"]))
    story.append(Spacer(1, 3))
    shown_any = False
    for label, key, table_rows in (("Best flight", "best_flight", report["flights"]), ("Best hotel", "best_hotel", report["hotels"])):
        pick = recs.get(key)
        if not pick:
            continue
        item = next((r for r in table_rows if r["option"] == pick["option"]), None)
        name = (item or {}).get("airline") or (item or {}).get("name") or ""
        story.append(Paragraph(f"<b>{label}:</b> option {pick['option']} - {_text(name)}", st["base"]))
        if pick.get("reason"):
            story.append(Paragraph(_text(pick["reason"]), st["bullet"], bulletText="-"))
        shown_any = True
    if recs.get("summary"):
        story.append(Paragraph(_text(recs["summary"]), st["base"]))
        shown_any = True
    if not shown_any:
        story.append(Paragraph("No recommendations could be produced from the returned data.", st["base"]))
    for warning in recs.get("warnings") or []:
        story.append(Paragraph(_text("Note: " + warning), st["small"]))

    # ---- Cost estimate
    story.append(Paragraph("Estimated trip cost", st["h2"]))
    scenarios = report["cost_estimate"]["scenarios"]
    if not scenarios:
        story.append(Paragraph("No estimate possible: no priced flight or hotel was returned.", st["base"]))
    for sc in scenarios:
        data = [[Paragraph("Item", st["head"]), Paragraph("Basis", st["head"]), Paragraph(f"Amount ({_text(currency)})", st["head"])]]
        for item in sc["items"]:
            data.append([Paragraph(_text(item["label"]), st["cell"]), Paragraph(_text(item["basis"]), st["cell"]), Paragraph(_text(fmt_money(item["amount"], currency)), st["cell"])])
        total_label = "Total of items above" + ("" if sc["complete"] else " (INCOMPLETE: flight or hotel price missing)")
        data.append([Paragraph(f"<b>{_text(total_label)}</b>", st["cell"]), "", Paragraph(f"<b>{_text(fmt_money(sc['total'], currency))}</b>", st["cell"])])
        block = [Paragraph(f"<b>{_text(sc['scenario'])}</b>", st["base"]), Spacer(1, 2), _table(data, [6.5 * cm, usable_width - 10 * cm, 3.5 * cm]), Spacer(1, 6)]
        story.append(KeepTogether(block))
    excluded = "; ".join(report["cost_estimate"]["excluded"])
    story.append(Paragraph(_text("Not included: " + excluded + "."), st["small"]))

    # ---- Flights
    story.append(Paragraph(f"Flight options ({len(report['flights'])})", st["h2"]))
    if not report["flights"]:
        story.append(Paragraph("No flight options were returned for this search.", st["base"]))
    else:
        keys = ["option", "airline", "flight_number", "departure", "arrival", "duration", "stops", "price"]
        cols = [c for c in FLIGHT_COLUMNS if c.key in keys]
        widths = [1.3, 2.6, 2.1, 2.6, 2.6, 1.7, 1.2, 1.7]
        data = [[Paragraph(_text(c.header), st["head"]) for c in cols] + [Paragraph("Link", st["head"])]]
        for row in report["flights"]:
            data.append([Paragraph(_text(display_value(row, c)), st["cell"]) for c in cols] + [Paragraph(_link(row.get("booking_url"), "Google Flights"), st["cell"])])
        scale = (usable_width - 2.0 * cm) / (sum(widths) * cm)
        story.append(_table(data, [w * cm * scale for w in widths] + [2.0 * cm]))
        story.append(Paragraph("Price is as returned by the provider for the submitted search; the link opens a Google Flights search for the whole query.", st["small"]))

    # ---- Hotels
    story.append(Paragraph(f"Hotel options ({len(report['hotels'])})", st["h2"]))
    if not report["hotels"]:
        story.append(Paragraph("No hotel options were returned for this search.", st["base"]))
    else:
        cols = [c for c in HOTEL_COLUMNS if c.key in ("option", "name", "rating", "price_per_night", "total_price")]
        widths = [1.3, 3.4, 1.4, 1.9, 1.8]
        head = [Paragraph(_text(c.header), st["head"]) for c in cols] + [Paragraph("Amenities", st["head"]), Paragraph("Link", st["head"])]
        data = [head]
        for row in report["hotels"]:
            am = row.get("amenities_list") or []
            am_text = ", ".join(am[:12]) + (f" (+{len(am) - 12} more)" if len(am) > 12 else "") if am else "n/a"
            data.append([Paragraph(_text(display_value(row, c)), st["cell"]) for c in cols] + [Paragraph(_text(am_text), st["cell"]), Paragraph(_link(row.get("booking_url"), "Open"), st["cell"])])
        fixed = sum(widths) * cm
        remaining = usable_width - fixed - 1.4 * cm
        story.append(_table(data, [w * cm for w in widths] + [remaining, 1.4 * cm]))

    # ---- Sources & notes
    story.append(Paragraph("Data sources", st["h2"]))
    for s in report["sources"] or []:
        retrieved = f" (retrieved {s['retrieved']})" if s.get("retrieved") else ""
        story.append(Paragraph(_text(f"{s['type']}: {s['name']}{retrieved}"), st["bullet"], bulletText="-"))
    if not report["sources"]:
        story.append(Paragraph("No source information available.", st["base"]))
    story.append(Paragraph("Important limitations and notes", st["h2"]))
    for note in report["notes"]:
        story.append(Paragraph(_text(note), st["bullet"], bulletText="-"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=clean_text(f"{report['title']} {route}"), author="AI Travel Analysis",
    )
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
