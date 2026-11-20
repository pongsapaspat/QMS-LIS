from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.time import format_datetime_for_web

THAI_FONT = Path("C:/Windows/Fonts/LeelawUI.ttf")
THAI_FONT_BOLD = Path("C:/Windows/Fonts/LeelaUIb.ttf")


def _register_fonts() -> None:
    if not THAI_FONT.exists() or not THAI_FONT_BOLD.exists():
        raise RuntimeError("Thai PDF fonts are not available")
    if "QMSLIS-Thai" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("QMSLIS-Thai", str(THAI_FONT)))
        pdfmetrics.registerFont(TTFont("QMSLIS-Thai-Bold", str(THAI_FONT_BOLD)))


def build_lab_report_pdf(context: dict[str, Any]) -> bytes:
    _register_fonts()
    buffer = BytesIO()
    order, patient, results = context["order"], context["patient"], context["results"]
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "ThaiNormal", parent=styles["Normal"], fontName="QMSLIS-Thai", fontSize=9, leading=13
    )
    bold = ParagraphStyle("ThaiBold", parent=normal, fontName="QMSLIS-Thai-Bold")
    title = ParagraphStyle("ThaiTitle", parent=bold, fontSize=18, leading=22, alignment=TA_CENTER)
    subtitle = ParagraphStyle(
        "ThaiSubtitle", parent=bold, fontSize=12, leading=16, alignment=TA_CENTER
    )
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"QMS-LIS {order.order_number}",
        author="QMS-LIS",
    )
    story: list[Any] = [
        Paragraph("QMS-LIS", title),
        Paragraph("รายงานผลการตรวจทางห้องปฏิบัติการ", subtitle),
        Spacer(1, 5 * mm),
    ]
    patient_data = [
        [
            Paragraph("ชื่อผู้ป่วย", bold),
            Paragraph(patient.display_name, normal),
            Paragraph("HN", bold),
            Paragraph(patient.hn, normal),
        ],
        [
            Paragraph("วันเกิด", bold),
            Paragraph(str(patient.date_of_birth or "-"), normal),
            Paragraph("เพศ", bold),
            Paragraph(patient.sex or "-", normal),
        ],
        [
            Paragraph("เลขที่ Order", bold),
            Paragraph(order.order_number, normal),
            Paragraph("ความเร่งด่วน", bold),
            Paragraph("ด่วน" if order.priority == "URGENT" else "ปกติ", normal),
        ],
        [
            Paragraph("เลขสิ่งส่งตรวจ", bold),
            Paragraph(", ".join(context["accession_numbers"]), normal),
            Paragraph("วันที่สั่งตรวจ", bold),
            Paragraph(format_datetime_for_web(order.ordered_at), normal),
        ],
        [Paragraph("ข้อมูลทางคลินิก", bold), Paragraph(order.clinical_note or "-", normal), "", ""],
    ]
    patient_table = Table(patient_data, colWidths=[27 * mm, 65 * mm, 27 * mm, 55 * mm])
    patient_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ced4da")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f5f7")),
                ("BACKGROUND", (2, 0), (2, -2), colors.HexColor("#f3f5f7")),
                ("SPAN", (1, 4), (3, 4)),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([patient_table, Spacer(1, 6 * mm)])
    if getattr(order, 'package_snapshots', None):
        from xml.sax.saxutils import escape

        names = ', '.join(p['name'] for p in order.package_snapshots)
        story.extend([Paragraph(f'Package: {escape(names)}', normal), Spacer(1, 3 * mm)])
    rows = [[Paragraph(x, bold) for x in ("รายการตรวจ", "ผลตรวจ", "หน่วย", "ช่วงอ้างอิง", "สถานะ")]]
    for result in results:
        if result.get('parameters'):
            rows.append([Paragraph(result['test_name'], bold), '', '', '', ''])
            for parameter in result['parameters']:
                rows.append([
                    Paragraph(parameter['name'], normal), Paragraph(parameter['value'], normal),
                    Paragraph((parameter['unit'] or '-').replace('⁶', '<super>6</super>')
                              .replace('³', '<super>3</super>'), normal),
                    Paragraph(parameter['reference'] or '-', normal),
                    Paragraph(parameter['flag'] or '-', normal),
                ])
            continue
        flag = result["abnormal_flag"]
        status_text = "ค่าวิกฤต" if flag in {"LL", "HH"} else "ผิดปกติ" if flag in {"L", "H"} else "ปกติ"
        rows.append(
            [
                Paragraph(
                    f'{result["test_name"]}<br/><font size="7">{result["test_code"]}</font>', normal
                ),
                Paragraph(
                    str(result["result_value"] or "-"), bold if flag in {"LL", "HH"} else normal
                ),
                Paragraph(result["unit"] or "-", normal),
                Paragraph(result["reference_text"] or "-", normal),
                Paragraph(status_text, normal),
            ]
        )
    table = Table(rows, repeatRows=1, colWidths=[56 * mm, 35 * mm, 24 * mm, 38 * mm, 25 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#adb5bd")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([table, Spacer(1, 7 * mm)])
    approvals = Table(
        [
            [Paragraph("รายงานผลโดย", bold), Paragraph("อนุมัติผลโดย", bold)],
            [
                Paragraph(
                    f"{context.get('reported_by') or '-'}<br/>"
                    f"{format_datetime_for_web(context.get('reported_at'))}",
                    normal,
                ),
                Paragraph(
                    f"{order.released_by or '-'}<br/>{format_datetime_for_web(order.released_at)}",
                    normal,
                ),
            ],
        ],
        colWidths=[89 * mm, 89 * mm],
    )
    approvals.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#6c757d")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(approvals)

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("QMSLIS-Thai", 8)
        canvas.setFillColor(colors.HexColor("#6c757d"))
        canvas.drawString(14 * mm, 8 * mm, "รายงานนี้สร้างจากระบบ QMS-LIS")
        canvas.drawRightString(196 * mm, 8 * mm, f"หน้า {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
