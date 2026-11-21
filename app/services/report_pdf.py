"""Reports styled after the supplied laboratory paper forms."""

from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.time import format_datetime_for_web

FONT_DIR = Path(__file__).resolve().parents[1] / "static" / "fonts" / "th-sarabun-psk"
THAI_FONT = FONT_DIR / "THSarabunPSK.ttf"
THAI_FONT_BOLD = FONT_DIR / "THSarabunPSK-Bold.ttf"
SYMBOL_FONT = Path("C:/Windows/Fonts/seguisym.ttf")


def _register_fonts() -> None:
    if not THAI_FONT.exists() or not THAI_FONT_BOLD.exists():
        raise RuntimeError("Thai PDF fonts are not available")
    if "QMSLIS-Thai" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("QMSLIS-Thai", str(THAI_FONT)))
        pdfmetrics.registerFont(TTFont("QMSLIS-Thai-Bold", str(THAI_FONT_BOLD)))
    if SYMBOL_FONT.exists() and "QMSLIS-Symbol" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("QMSLIS-Symbol", str(SYMBOL_FONT)))


def build_lab_report_pdf(context: dict[str, Any]) -> bytes:
    _register_fonts()
    buffer = BytesIO()
    order, patient, lab = context["order"], context["patient"], context["lab"]
    normal = ParagraphStyle(
        "Form",
        fontName="QMSLIS-Thai",
        fontSize=14,
        leading=15,
        textColor=colors.black,
        shaping=1,
    )
    heading = ParagraphStyle(
        "FormTitle",
        parent=normal,
        fontName="QMSLIS-Thai-Bold",
        fontSize=16,
        leading=18,
        alignment=TA_CENTER,
    )
    subtitle = ParagraphStyle(
        "FormSubtitle", parent=normal, fontSize=16, leading=18, alignment=TA_CENTER
    )
    small = ParagraphStyle("FormSmall", parent=normal, fontSize=12, leading=11)

    def p(value: Any, style: ParagraphStyle = normal) -> Paragraph:
        text = escape(str(value if value is not None else "-")).replace("\n", "<br/>")
        return Paragraph(text, style)

    def result_value(value: Any, flag: str | None) -> Paragraph:
        text = escape(str(value if value is not None else "-"))
        if flag in {"H", "L", "HH", "LL", "A"}:
            text += f" <super>{escape(flag)}</super>"
        return Paragraph(text, normal)

    def unit_value(value: str | None) -> Paragraph:
        text = escape(value or "-")
        for superscript, digit in zip("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789", strict=True):
            text = text.replace(superscript, f'<super size="9.8" rise="4.2">{digit}</super>')
        return Paragraph(text, normal)

    def checkbox(checked: bool = False) -> str:
        if "QMSLIS-Symbol" in pdfmetrics.getRegisteredFontNames():
            return '<font name="QMSLIS-Symbol">' + ("☒" if checked else "☐") + "</font>"
        return "[X]" if checked else "[ ]"

    # Match the reference's Letter sheet, header at x49/y70 and 516pt width.
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=43,
        rightMargin=43,
        topMargin=64,
        bottomMargin=48,
        title=f"QMS-LIS {order.order_number}",
        author=lab["name"],
    )
    width = 514
    story: list[Any] = []
    for index, section in enumerate(context["sections"]):
        if index:
            story.append(PageBreak())
        specimens = section["specimens"]
        types = ", ".join(dict.fromkeys(s.specimen_type_name_en for s in specimens))
        accessions = "\n".join(s.accession_number for s in specimens) or "-"
        received = (
            "\n".join(dict.fromkeys(format_datetime_for_web(s.received_at) for s in specimens))
            or "-"
        )
        age = context["patient_age"]
        header = Table(
            [
                [
                    p("คลินิกเทคนิคการแพทย์: " + lab["name"]),
                    p("ชื่อ-สกุล: " + patient.display_name),
                    p(f"อายุ: {age if age is not None else '-'} ปี"),
                ],
                [
                    p("ที่อยู่: " + (lab["address"] or "-")),
                    p("HN: " + patient.hn),
                    p("เพศ: " + (patient.sex or "-")),
                ],
                [p("โทรศัพท์: " + (lab["phone"] or "-")), p("ผู้ส่งตรวจ: -"), ""],
                [
                    p(section["report_title"], heading),
                    p("Requested Date/Time:\n" + format_datetime_for_web(order.ordered_at), small),
                    p("ประเภทสิ่งส่งตรวจ:\n" + (types or "-"), small),
                ],
                [
                    p(section["report_subtitle"], subtitle),
                    p("Received Date/Time:\n" + received, small),
                    p("เลขที่สิ่งส่งตรวจ:\n" + accessions, small),
                ],
            ],
            colWidths=[213, 166, 135],
            minRowHeights=[24, 24, 24, 27, 27],
        )
        header.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                    ("LINEAFTER", (0, 0), (0, -1), 0.8, colors.black),
                    ("LINEBELOW", (0, 2), (0, 2), 0.8, colors.black),
                    ("SPAN", (1, 2), (2, 2)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.extend([header, Spacer(1, 21)])
        rows = [[p(label) for label in ("รายการตรวจ", "ผลตรวจ", "หน่วย", "ค่าอ้างอิง")]]
        for result in section["results"]:
            if result.get("parameters"):
                values = [
                    (r["name"], r["value"], r["unit"], r["reference"], r["flag"])
                    for r in result["parameters"]
                ]
            else:
                values = [
                    (
                        result.get("test_name_en") or result["test_name"],
                        result["result_value"],
                        result["unit"],
                        result["reference_text"],
                        result["abnormal_flag"],
                    )
                ]
            for name, value, unit, reference, flag in values:
                rows.append(
                    [p(name), result_value(value, flag), unit_value(unit), p(reference or "-")]
                )
        is_ua = section["subtitle"] == "Urinalysis"
        if is_ua:
            # The UA reference centers values, units and references, unlike Chemistry.
            ua_style = ParagraphStyle("UA", parent=normal, fontSize=12, leading=12)
            ua_center = ParagraphStyle("UACenter", parent=ua_style, alignment=TA_CENTER)
            rows = [[Paragraph(cell.text, ua_center) for cell in rows[0]]] + [
                [
                    Paragraph(cell.text, ua_style if col == 0 else ua_center)
                    for col, cell in enumerate(row)
                ]
                for row in rows[1:]
            ]
        table_width = width if is_ua else 470
        table = Table(
            rows,
            repeatRows=1,
            colWidths=[table_width / 4] * 4,
            minRowHeights=[24] + [21 if is_ua else 24] * (len(rows) - 1),
            hAlign="CENTER",
        )
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, 0), 0.6, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        # Keep the signature area at the reference position for shorter orders.
        table_height = table.wrap(table_width, doc.height)[1]
        story.append(Spacer(1, max(0, (402 if is_ua else 384) - table_height)))
        tail: list[Any] = [Spacer(1, 6)]
        if not is_ua:
            tail += [p("NOTE: H = ค่าสูงกว่าเกณฑ์ปกติ, L = ค่าต่ำกว่าเกณฑ์ปกติ", small), Spacer(1, 10)]
        tail += [
            Paragraph(
                "ส่งตรวจต่อห้องปฏิบัติการภายนอก:  "
                + checkbox(True)
                + " ไม่ใช่  "
                + checkbox()
                + " ใช่  ชื่อห้องปฏิบัติการ: ____________________",
                small,
            ),
            Spacer(1, 12),
            p(
                f"Reported by: {section['reported_by'] or '-'}"
                f"     Date: {format_datetime_for_web(section['reported_at'])}"
            ),
            Spacer(1, 10),
            p(
                f"Approved by: {order.released_by or '-'}"
                f"     Date: {format_datetime_for_web(order.released_at)}"
            ),
            Spacer(1, 10),
            Paragraph(
                "สถานะรายงาน: "
                + checkbox(True)
                + " Final   "
                + checkbox()
                + " Preliminary   "
                + checkbox()
                + " Corrected",
                normal,
            ),
        ]
        story.append(KeepTogether(tail))

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("QMSLIS-Thai", 10)
        canvas.drawString(49, 24, f"{order.order_number} / HN: {patient.hn}")
        canvas.drawRightString(563, 24, f"หน้า {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
