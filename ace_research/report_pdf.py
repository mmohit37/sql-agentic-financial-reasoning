"""
report_pdf.py

ReportLab (Platypus) financial report PDF generator.

generate_pdf(summary, narrative, output_path) -> None

Reads only from the summary dict produced by build_financial_summary()
and the narrative string produced by generate_narrative().
No database calls. No metric recomputation. No HTML.
"""

from __future__ import annotations

from typing import Optional

try:
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import pagesizes
    from reportlab.lib.units import inch
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


# =============================================================================
# Metric display configuration (standalone copy — no import from report.py)
# =============================================================================

_INCOME_METRICS  = ["revenue", "operating_income", "net_income"]
_BALANCE_METRICS = ["total_assets", "total_liabilities", "total_equity"]

_METRIC_LABELS: dict[str, str] = {
    "revenue":           "Revenue",
    "operating_income":  "Operating Income",
    "net_income":        "Net Income",
    "total_assets":      "Total Assets",
    "total_liabilities": "Total Liabilities",
    "total_equity":      "Total Equity",
    "gross_margin":      "Gross Margin",
    "operating_margin":  "Operating Margin",
    "net_margin":        "Net Margin",
    "current_ratio":     "Current Ratio",
    "piotroski_score":   "Piotroski F-Score",
    # Extended metrics (Phase B)
    "asset_turnover":    "Asset Turnover",
    "return_on_assets":  "Return on Assets",
    "return_on_equity":  "Return on Equity",
    "debt_ratio":        "Debt Ratio",
    "quick_ratio":       "Quick Ratio",
}

# Keys in quality_metrics that are not tabular metric dicts (skip in table loops)
_NON_METRIC_KEYS: frozenset = frozenset({"risk_flags"})

# Preferred display order for the Financial Quality table.
# Any metric in quality_metrics that is not listed here is appended after
# this sequence (excluding _NON_METRIC_KEYS). piotroski_score is last so the
# bold_last table style highlights it.
_QUALITY_DISPLAY_ORDER: list = [
    "gross_margin", "operating_margin", "net_margin",
    "current_ratio", "quick_ratio",
    "asset_turnover", "return_on_assets", "return_on_equity", "debt_ratio",
    "piotroski_score",
]

# Metrics whose values are stored as decimal ratios and displayed as percentages
_PCT_QUALITY_METRICS: frozenset = frozenset({
    "gross_margin", "operating_margin", "net_margin",
    "return_on_assets", "return_on_equity", "debt_ratio",
})


# =============================================================================
# Format helpers  (pure functions — no ReportLab dependency)
# =============================================================================

def _fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        s = f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}B"
    if abs_v >= 1_000_000:
        s = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if abs_v >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    s = f"{value * 100:.1f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _fmt_ratio(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _fmt_yoy(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    s = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{sign}{s}%"


def _fmt_score(value: object) -> str:
    return str(value) if value is not None else "N/A"


def _fmt_quality_value(metric: str, value: Optional[float]) -> str:
    """Choose the right formatter for a quality metric value."""
    if metric == "piotroski_score":
        return _fmt_score(value)
    if metric in _PCT_QUALITY_METRICS:
        return _fmt_pct(value)
    return _fmt_ratio(value)   # ratios: current_ratio, quick_ratio, asset_turnover, etc.


# =============================================================================
# Private ReportLab helpers
# =============================================================================

def _col_widths(n_years: int, has_yoy: bool = True) -> list:
    """Compute column widths for a standard financial table (6.5-inch body)."""
    available = 6.5 * inch
    label_w   = 2.0 * inch
    yoy_w     = 1.0 * inch if has_yoy else 0.0
    remaining = available - label_w - yoy_w
    year_w    = (remaining / n_years) if n_years > 0 else remaining
    widths = [label_w] + [year_w] * n_years
    if has_yoy:
        widths.append(yoy_w)
    return widths


def _base_table_style(n_total_rows: int, bold_last: bool = False) -> list:
    """Standard TableStyle commands for a financial table."""
    cmds = [
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf8")),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 10),
        ("LINEBELOW",  (0, 0), (-1, 0), 1.5, colors.HexColor("#8a9dbf")),
        # Body
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 9),
        # Grid
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ef")),
        # Alignment
        ("ALIGN",      (0, 0), (0, -1),  "LEFT"),
        ("ALIGN",      (1, 0), (-1, -1), "RIGHT"),
        # Padding
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]
    if bold_last and n_total_rows > 1:
        last = n_total_rows - 1
        cmds.extend([
            ("FONTNAME",  (0, last), (-1, last), "Helvetica-Bold"),
            ("LINEABOVE", (0, last), (-1, last), 1.5, colors.HexColor("#8a9dbf")),
            ("LINEBELOW", (0, last), (-1, last), 1.5, colors.HexColor("#8a9dbf")),
        ])
    return cmds


def _make_income_table(income: dict, years: list) -> "Table":
    """Build the Income Statement Platypus Table."""
    header = ["Metric"] + [str(yr) for yr in years] + ["YoY %"]
    data   = [header]
    for metric in _INCOME_METRICS:
        entry = income.get(metric, {})
        vals  = entry.get("values", {})
        yoy   = entry.get("yoy_pct")
        label = _METRIC_LABELS.get(metric, metric)
        data.append([label] + [_fmt_num(vals.get(yr)) for yr in years] + [_fmt_yoy(yoy)])
    return Table(
        data,
        colWidths=_col_widths(len(years), has_yoy=True),
        repeatRows=1,
        style=TableStyle(_base_table_style(len(data), bold_last=True)),
    )


def _make_balance_table(balance: dict, years: list) -> "Table":
    """Build the Balance Sheet Platypus Table."""
    header = ["Metric"] + [str(yr) for yr in years]
    data   = [header]
    for metric in _BALANCE_METRICS:
        entry = balance.get(metric, {})
        vals  = entry.get("values", {})
        label = _METRIC_LABELS.get(metric, metric)
        data.append([label] + [_fmt_num(vals.get(yr)) for yr in years])
    return Table(
        data,
        colWidths=_col_widths(len(years), has_yoy=False),
        repeatRows=1,
        style=TableStyle(_base_table_style(len(data), bold_last=True)),
    )


def _make_quality_table(quality: dict, years: list) -> "Table":
    """
    Build the Financial Quality Platypus Table dynamically.

    Iterates over all metric dicts in quality_metrics (skipping non-tabular keys
    such as risk_flags). Display order follows _QUALITY_DISPLAY_ORDER; any metric
    not listed there is appended after the preferred set. The Piotroski F-Score row
    is always rendered last and is highlighted by bold_last=True.

    Formatters are chosen per metric:
        _PCT_QUALITY_METRICS  -> _fmt_pct  (decimal ratio shown as %)
        piotroski_score       -> _fmt_score (integer)
        everything else       -> _fmt_ratio (plain decimal)
    """
    header = ["Metric"] + [str(yr) for yr in years]
    data   = [header]

    # Build ordered key list: preferred order (if present) then unknown extras
    extra_keys = [
        k for k in quality
        if k not in _NON_METRIC_KEYS
        and k not in _QUALITY_DISPLAY_ORDER
        and isinstance(quality[k], dict)
    ]
    display_keys = [k for k in _QUALITY_DISPLAY_ORDER if k in quality] + extra_keys

    for metric in display_keys:
        entry = quality[metric]
        if not isinstance(entry, dict):
            continue
        vals  = entry.get("values", {})
        label = _METRIC_LABELS.get(metric, metric.replace("_", " ").title())
        data.append([label] + [_fmt_quality_value(metric, vals.get(yr)) for yr in years])

    return Table(
        data,
        colWidths=_col_widths(len(years), has_yoy=False),
        repeatRows=1,
        style=TableStyle(_base_table_style(len(data), bold_last=True)),
    )


# =============================================================================
# Public API — PDF Generator
# =============================================================================

def generate_pdf(summary: dict, narrative: str, output_path: str) -> None:
    """
    Generate a PDF financial report and write it to output_path.

    Uses ReportLab Platypus. Raises ImportError if ReportLab is not installed.

    No DB calls. No metric recomputation.

    Sections:
        1  Title (company + year range)
        2  Executive Overview (narrative paragraph)
        3  Income Statement table  (Metric + years + YoY %)
        4  Balance Sheet table
        5  Financial Quality table (margins as %, ratio as decimal, Piotroski)
        6  Risk Flags (green "no flags" or red bullet list)
    """
    if not _REPORTLAB_AVAILABLE:
        raise ImportError(
            "ReportLab is required for PDF generation. "
            "Install with: pip install reportlab"
        )

    company = summary.get("company", "")
    years   = summary.get("years", [])
    income  = summary.get("income_statement", {})
    balance = summary.get("balance_sheet", {})
    quality = summary.get("quality_metrics", {})

    doc = SimpleDocTemplate(
        output_path,
        pagesize=pagesizes.LETTER,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        spaceAfter=4,
        textColor=colors.HexColor("#1a3a6e"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        spaceAfter=4,
    )
    units_style = ParagraphStyle(
        "ReportUnits",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#999999"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=18,
        spaceAfter=6,
        textColor=colors.HexColor("#1a3a6e"),
    )
    narrative_style = ParagraphStyle(
        "Narrative",
        parent=styles["Normal"],
        fontSize=10,
        leading=16,
        spaceAfter=12,
        leftIndent=12,
        rightIndent=12,
    )
    risk_clear_style = ParagraphStyle(
        "RiskClear",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1e7e34"),
        spaceAfter=6,
    )
    risk_flag_style = ParagraphStyle(
        "RiskFlag",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#c0392b"),
        spaceAfter=4,
    )
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#888888"),
        alignment=2,  # right-align
    )

    story = []

    # ── 1. Title ──────────────────────────────────────────────────────────────
    if len(years) >= 2:
        year_range = f"{years[0]}-{years[-1]}"
    elif years:
        year_range = str(years[0])
    else:
        year_range = "N/A"

    story.append(Paragraph(f"Financial Summary: {company}", title_style))
    story.append(Paragraph(f"Years covered: {year_range}", subtitle_style))
    story.append(Paragraph("(USD, billions unless otherwise noted)", units_style))
    story.append(Spacer(1, 0.15 * inch))

    # ── 2. Executive Overview ─────────────────────────────────────────────────
    story.append(Paragraph("Executive Overview", section_style))
    # Split narrative on newlines so LLM bullet points render as individual
    # paragraphs. Suppress a leading "Executive Overview" header line if the
    # LLM echoed it (the section heading is already added above).
    narrative_lines = [ln.strip() for ln in narrative.splitlines() if ln.strip()]
    if narrative_lines and narrative_lines[0].lower() == "executive overview":
        narrative_lines = narrative_lines[1:]
    for line in narrative_lines:
        story.append(Paragraph(line, narrative_style))

    # ── 3. Income Statement ───────────────────────────────────────────────────
    story.append(Paragraph("Income Statement", section_style))
    story.append(_make_income_table(income, years))
    story.append(Spacer(1, 0.1 * inch))

    # ── 4. Balance Sheet ──────────────────────────────────────────────────────
    story.append(Paragraph("Balance Sheet", section_style))
    story.append(_make_balance_table(balance, years))
    story.append(Spacer(1, 0.1 * inch))

    # ── 5. Financial Quality ──────────────────────────────────────────────────
    story.append(Paragraph("Financial Quality", section_style))
    story.append(_make_quality_table(quality, years))
    story.append(Spacer(1, 0.15 * inch))

    # ── 6. Risk Assessment ────────────────────────────────────────────────────
    latest        = years[-1] if years else None
    risk_analysis = summary.get("risk_analysis")

    if latest is not None and risk_analysis is not None:
        # Structured risk assessment from risk_engine.analyze_risk()
        overall_level = risk_analysis.get("overall_level", "Unknown")
        overall_score = risk_analysis.get("overall_score", 0)
        categories    = risk_analysis.get("categories", [])

        story.append(Paragraph(f"Risk Assessment ({latest})", section_style))

        summary_style = ParagraphStyle(
            "RiskSummary",
            parent=styles["Normal"],
            fontSize=10,
            spaceAfter=4,
            leftIndent=12,
        )
        story.append(Paragraph(f"Overall Risk Level: <b>{overall_level}</b>", summary_style))
        story.append(Paragraph(f"Composite Score: {overall_score:+d}", summary_style))
        story.append(Spacer(1, 0.08 * inch))

        for cat in categories:
            name     = cat.get("name", "")
            score    = cat.get("score", 0)
            severity = cat.get("severity", "stable").capitalize()
            style    = risk_clear_style if score >= 0 else risk_flag_style
            story.append(
                Paragraph(f"\u2022 {name} \u2014 {severity} ({score:+d})", style)
            )

    elif latest is not None:
        # Fallback: display legacy risk_flags list
        flags = quality.get("risk_flags", [])
        if flags:
            story.append(Paragraph(f"Risk Flags ({latest}):", section_style))
            for flag in sorted(flags):
                story.append(Paragraph(f"\u2022 {flag}", risk_flag_style))
        else:
            story.append(
                Paragraph(
                    "No material financial risk flags detected.",
                    risk_clear_style,
                )
            )

    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph("Generated by ACE Research Financial Reporter", footer_style)
    )

    doc.build(story)
