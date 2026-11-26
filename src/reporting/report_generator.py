"""Professional PDF report generation using ReportLab."""

from collections import Counter
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.storage.database import DatabaseManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _fmt_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


class ReportGenerator:
    """Builds a structured PDF monitoring report from SQLite session records."""

    def __init__(
        self,
        db: DatabaseManager,
        reports_dir: Path | str = "reports",
        evidence_dir: Path | str | None = None,
    ) -> None:
        self._db = db
        self._reports_dir = Path(reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._evidence_dir = (
            Path(evidence_dir)
            if evidence_dir is not None
            else self._reports_dir.parent / "evidence"
        )

    def _resolve_screenshot(self, raw_path: str, session_id: int) -> Path | None:
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if candidate.exists():
            return candidate
        fallback = self._evidence_dir / f"session_{session_id}" / candidate.name
        if fallback.exists():
            return fallback
        return None

    @staticmethod
    def _fit_image_size(
        image_path: Path, max_w: float, max_h: float
    ) -> tuple[float, float]:
        try:
            with PILImage.open(image_path) as im:
                w, h = im.size
            if w > 0 and h > 0:
                scale = min(max_w / float(w), max_h / float(h))
                return w * scale, h * scale
        except Exception:
            pass
        return max_w, max_h * 0.85

    def generate(self, session_id: int) -> Path:
        """Generate a PDF report for ``session_id`` and record it in SQLite."""
        session = self._db.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found.")
        events = self._db.get_session_events(session_id)

        pdf_path = self._reports_dir / f"exam_report_session_{session_id}.pdf"
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            fontSize=18,
            textColor=colors.HexColor("#1B365D"),
            alignment=1,
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#5B6B7C"),
            alignment=1,
            spaceAfter=14,
        )
        section_style = ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading2"],
            fontSize=12,
            textColor=colors.HexColor("#1B365D"),
            spaceBefore=12,
            spaceAfter=6,
        )
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=styles["Italic"],
            fontSize=9,
            textColor=colors.HexColor("#4A5568"),
            alignment=1,
            spaceBefore=16,
        )

        elements: list[Any] = [
            Paragraph("EXAM MONITORING REPORT", title_style),
            Paragraph(
                "HABUSH CMS — AI-Based Smart Exam Cheating Detection System",
                subtitle_style,
            ),
        ]

        # Session details table
        details_data = [
            [
                "Session:",
                f"Exam_Session_{session_id:02d}",
                "Mode:",
                str(session.get("mode", "")).capitalize(),
            ],
            [
                "Source:",
                str(session.get("source_name", "")),
                "Date:",
                str(session.get("start_time", "")),
            ],
            [
                "Duration:",
                _fmt_duration(float(session.get("duration_sec") or 0.0)),
                "People detected:",
                str(session.get("total_people", 0)),
            ],
            [
                "Campus:",
                str(session.get("campus") or "Not specified"),
                "Controller:",
                str(session.get("user_email") or "Not specified"),
            ],
        ]
        details_table = Table(details_data, colWidths=[75, 175, 90, 155])
        details_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F7FA")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1A202C")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("PADDING", (0, 0), (-1, -1), 6),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
                ]
            )
        )
        elements.append(details_table)
        elements.append(Spacer(1, 10))

        # Summary
        phone_count = sum(
            1 for e in events if "phone" in str(e.get("category", "")).lower()
        )
        elements.append(Paragraph("Summary", section_style))
        elements.append(
            Paragraph(
                f"Total suspicious events: <b>{len(events)}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Phone detections: <b>{phone_count}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Highest risk: <b>{session.get('max_risk', 'Low')}</b>",
                styles["Normal"],
            )
        )

        # Events by category
        elements.append(Paragraph("Events by Category", section_style))
        counts = Counter(e.get("category", "Other") for e in events)
        if counts:
            cat_rows = [["Indicator Category", "Count"]] + [
                [cat, str(cnt)] for cat, cnt in counts.most_common()
            ]
            cat_table = Table(cat_rows, colWidths=[350, 145])
            cat_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E0")),
                        ("PADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            elements.append(cat_table)
        else:
            elements.append(
                Paragraph("No suspicious indicators were flagged in this session.", styles["Normal"])
            )

        # Event log
        elements.append(Paragraph("Event Log", section_style))
        resolved_shots: list[tuple[Path, str]] = []
        if events:
            cell_style = ParagraphStyle(
                "LogCell",
                parent=styles["Normal"],
                fontSize=8.2,
                leading=10,
                textColor=colors.HexColor("#1A202C"),
            )
            log_rows = [["Time", "Indicator", "Student", "Score", "Level", "Screenshot"]]
            for evt in events:
                sp = self._resolve_screenshot(str(evt.get("screenshot_path", "")), session_id)
                if sp is not None:
                    caption_text = (
                        f"{_fmt_duration(float(evt.get('timestamp_sec') or 0.0))} — "
                        f"{evt.get('category', '')} (Person {evt.get('track_id', '')}, "
                        f"{evt.get('risk_level', 'Low')} / {evt.get('risk_score', 0)})"
                    )
                    resolved_shots.append((sp, caption_text))

            for evt in events[:80]:
                sp = self._resolve_screenshot(str(evt.get("screenshot_path", "")), session_id)
                log_rows.append(
                    [
                        _fmt_duration(float(evt.get("timestamp_sec") or 0.0)),
                        Paragraph(escape(str(evt.get("category", ""))), cell_style),
                        f"Person {evt.get('track_id', '')}",
                        str(evt.get("risk_score", 0)),
                        str(evt.get("risk_level", "Low")),
                        "Attached" if sp is not None else "—",
                    ]
                )
            log_table = Table(log_rows, colWidths=[58, 172, 72, 52, 65, 76])
            log_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E0")),
                        ("PADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            elements.append(log_table)
        else:
            elements.append(
                Paragraph("No suspicious events were recorded in this session.", styles["Normal"])
            )

        # Fallback: include session snapshot or any session screenshots on disk if none linked
        if not resolved_shots:
            session_dir = self._evidence_dir / f"session_{session_id}"
            if session_dir.exists():
                for img_file in sorted(session_dir.glob("*.png")):
                    resolved_shots.append(
                        (img_file, f"Session Snapshot — {session.get('source_name', '')}")
                    )

        # Evidence screenshots (all available screenshots for this record)
        if resolved_shots:
            elements.append(Paragraph(f"Evidence Screenshots ({len(resolved_shots)})", section_style))
            cap_style = ParagraphStyle(
                "Cap",
                parent=styles["Normal"],
                fontSize=7.8,
                leading=10,
                textColor=colors.HexColor("#1A202C"),
            )
            img_cells = []
            row: list[Any] = []
            for img_path, caption_text in resolved_shots:
                w, h = self._fit_image_size(img_path, max_w=2.3 * inch, max_h=1.65 * inch)
                img = Image(str(img_path), width=w, height=h)
                caption = Paragraph(escape(caption_text), cap_style)
                row.append([img, Spacer(1, 3), caption])
                if len(row) == 2:
                    img_cells.append(row)
                    row = []
            if row:
                while len(row) < 2:
                    row.append("")
                img_cells.append(row)

            shot_table = Table(img_cells, colWidths=[247, 247])
            shot_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E0")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                        ("PADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            elements.append(shot_table)

        elements.append(
            Paragraph(
                "Suspicious indicator – human verification required. "
                "All entries are automated indicators and not a final cheating verdict.",
                disclaimer_style,
            )
        )

        doc.build(elements)
        self._db.add_report(session_id, str(pdf_path))
        logger.info("Generated PDF report: %s", pdf_path)
        return pdf_path
