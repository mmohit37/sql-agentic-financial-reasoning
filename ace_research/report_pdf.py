"""
report_pdf.py

HTML + PDF financial report generator.

Part 1: render_html_report(summary, narrative) -> str
Part 2: generate_pdf(summary, narrative, output_path)

Reads only from the summary dict produced by build_financial_summary()
and the narrative string produced by generate_narrative().
No database calls. No metric recomputation.
"""

from __future__ import annotations

import html as _html_lib
from typing import Optional

# WeasyPrint is optional. The module is importable without it; only
# generate_pdf() raises ImportError when WeasyPrint is absent.
try:
    from weasyprint import HTML as _WeasyHTML
    _WEASYPRINT_AVAILABLE = True
except ImportError:
    _WeasyHTML = None  # type: ignore[assignment,misc]
    _WEASYPRINT_AVAILABLE = False


# =============================================================================
# Metric display configuration (standalone copy — no import from report.py)
# =============================================================================

_INCOME_METRICS = ["revenue", "operating_income", "net_income"]
_BALANCE_METRICS = ["total_assets", "total_liabilities", "total_equity"]
_QUALITY_MARGIN_METRICS = ["gross_margin", "operating_margin", "net_margin"]

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
}


# =============================================================================
# Format helpers  (mirrored from report.py — no shared import needed)
# =============================================================================

def _e(text: object) -> str:
    """HTML-escape any value for safe insertion into HTML."""
    return _html_lib.escape(str(text))


def _fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_ratio(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _fmt_yoy(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_score(value: object) -> str:
    return str(value) if value is not None else "N/A"


def _yoy_css_class(value: Optional[float]) -> str:
    """Return the CSS class that colours a YoY value."""
    if value is None:
        return "yoy-neutral"
    return "yoy-pos" if value >= 0 else "yoy-neg"


# =============================================================================
# Inline CSS
# =============================================================================

_CSS = """\
body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 12pt;
    color: #1a1a2e;
    margin: 40px;
}
.report-title {
    font-size: 22pt;
    font-weight: bold;
    color: #1a3a6e;
    margin-bottom: 2px;
}
.report-subtitle {
    font-size: 11pt;
    color: #666;
    margin-top: 0;
    margin-bottom: 20px;
}
hr.divider {
    border: none;
    border-top: 1px solid #c8d0e0;
    margin: 20px 0;
}
.section-header {
    font-size: 14pt;
    font-weight: bold;
    color: #1a3a6e;
    margin-top: 28px;
    margin-bottom: 8px;
    padding-bottom: 4px;
    border-bottom: 2px solid #1a3a6e;
}
.narrative-box {
    background-color: #f0f4fc;
    border-left: 4px solid #1a3a6e;
    padding: 14px 18px;
    margin: 12px 0;
    font-size: 11pt;
    line-height: 1.7;
    color: #2c2c2c;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    font-size: 11pt;
}
thead th {
    background-color: #e8edf8;
    font-weight: bold;
    padding: 8px 10px;
    border-bottom: 2px solid #8a9dbf;
    text-align: right;
}
thead th.col-label { text-align: left; }
tbody td {
    padding: 6px 10px;
    border-bottom: 1px solid #dde3ef;
    text-align: right;
}
tbody td.col-label { text-align: left; }
tr.total-row td {
    font-weight: bold;
    border-top: 2px solid #8a9dbf;
    border-bottom: 2px solid #8a9dbf;
}
.yoy-pos    { color: #1e7e34; }
.yoy-neg    { color: #c0392b; }
.yoy-neutral{ color: #888;    }
.risk-present {
    background-color: #fff0f0;
    border-left: 4px solid #c0392b;
    padding: 10px 14px;
    margin-top: 12px;
}
.risk-clear {
    background-color: #f0fff4;
    border-left: 4px solid #1e7e34;
    padding: 10px 14px;
    margin-top: 12px;
}
.risk-label { font-weight: bold; }
.risk-item  { color: #c0392b; font-weight: bold; }
.footer {
    margin-top: 40px;
    padding-top: 10px;
    border-top: 1px solid #ccc;
    font-size: 9pt;
    color: #888;
    text-align: right;
}
"""


# =============================================================================
# Private HTML fragment builders
# =============================================================================

def _th(label: str, align_left: bool = False) -> str:
    cls = ' class="col-label"' if align_left else ""
    return f"<th{cls}>{_e(label)}</th>"


def _td(content: str, align_left: bool = False) -> str:
    cls = ' class="col-label"' if align_left else ""
    return f"<td{cls}>{content}</td>"


def _income_table(income: dict, years: list) -> str:
    """Build the Income Statement HTML table."""
    parts = ["<table>", "<thead><tr>"]
    parts.append(_th("Metric", align_left=True))
    for yr in years:
        parts.append(_th(str(yr)))
    parts.append(_th("YoY %"))
    parts.append("</tr></thead>", )
    parts.append("<tbody>")

    for idx, metric in enumerate(_INCOME_METRICS):
        entry = income.get(metric, {})
        vals  = entry.get("values", {})
        yoy   = entry.get("yoy_pct")
        label = _METRIC_LABELS.get(metric, metric)
        is_last = idx == len(_INCOME_METRICS) - 1
        row_cls = ' class="total-row"' if is_last else ""

        parts.append(f"<tr{row_cls}>")
        parts.append(_td(_e(label), align_left=True))
        for yr in years:
            parts.append(_td(_e(_fmt_num(vals.get(yr)))))
        yoy_cls = _yoy_css_class(yoy)
        parts.append(f'<td class="{yoy_cls}">{_e(_fmt_yoy(yoy))}</td>')
        parts.append("</tr>")

    parts.append("</tbody></table>")
    return "\n".join(parts)


def _balance_table(balance: dict, years: list) -> str:
    """Build the Balance Sheet HTML table."""
    parts = ["<table>", "<thead><tr>"]
    parts.append(_th("Metric", align_left=True))
    for yr in years:
        parts.append(_th(str(yr)))
    parts.append("</tr></thead>")
    parts.append("<tbody>")

    for idx, metric in enumerate(_BALANCE_METRICS):
        entry = balance.get(metric, {})
        vals  = entry.get("values", {})
        label = _METRIC_LABELS.get(metric, metric)
        is_last = idx == len(_BALANCE_METRICS) - 1
        row_cls = ' class="total-row"' if is_last else ""

        parts.append(f"<tr{row_cls}>")
        parts.append(_td(_e(label), align_left=True))
        for yr in years:
            parts.append(_td(_e(_fmt_num(vals.get(yr)))))
        parts.append("</tr>")

    parts.append("</tbody></table>")
    return "\n".join(parts)


def _quality_table(quality: dict, years: list) -> str:
    """Build the Financial Quality HTML table."""
    parts = ["<table>", "<thead><tr>"]
    parts.append(_th("Metric", align_left=True))
    for yr in years:
        parts.append(_th(str(yr)))
    parts.append("</tr></thead>")
    parts.append("<tbody>")

    # Margin ratios (displayed as %)
    for metric in _QUALITY_MARGIN_METRICS:
        entry = quality.get(metric, {})
        vals  = entry.get("values", {})
        label = _METRIC_LABELS.get(metric, metric)
        parts.append("<tr>")
        parts.append(_td(_e(label), align_left=True))
        for yr in years:
            parts.append(_td(_e(_fmt_pct(vals.get(yr)))))
        parts.append("</tr>")

    # Current ratio (plain decimal)
    cr_entry = quality.get("current_ratio", {})
    cr_vals  = cr_entry.get("values", {})
    parts.append("<tr>")
    parts.append(_td(_e(_METRIC_LABELS["current_ratio"]), align_left=True))
    for yr in years:
        parts.append(_td(_e(_fmt_ratio(cr_vals.get(yr)))))
    parts.append("</tr>")

    # Piotroski score — summary row, displayed bold
    pio_entry = quality.get("piotroski_score", {})
    pio_vals  = pio_entry.get("values", {})
    parts.append('<tr class="total-row">')
    parts.append(_td(_e(_METRIC_LABELS["piotroski_score"]), align_left=True))
    for yr in years:
        parts.append(_td(_e(_fmt_score(pio_vals.get(yr)))))
    parts.append("</tr>")

    parts.append("</tbody></table>")
    return "\n".join(parts)


def _risk_section(quality: dict, years: list) -> str:
    """Build the risk flags box below the Financial Quality table."""
    flags  = quality.get("risk_flags", [])
    latest = years[-1] if years else None
    if latest is None:
        return ""

    if flags:
        items = "".join(
            f'<li class="risk-item">{_e(flag)}</li>'
            for flag in sorted(flags)
        )
        return (
            f'<div class="risk-present">'
            f'<span class="risk-label">Risk Flags ({_e(str(latest))}):</span>'
            f"<ul>{items}</ul>"
            f"</div>"
        )

    return (
        f'<div class="risk-clear">'
        f'<span class="risk-label">Risk Flags ({_e(str(latest))}):</span> '
        f"No financial risk flags detected."
        f"</div>"
    )


# =============================================================================
# Part 1 — HTML Renderer
# =============================================================================

def render_html_report(summary: dict, narrative: str) -> str:
    """
    Render a financial summary dict and narrative string into a styled HTML
    string suitable for display or PDF conversion.

    Sections:
        Title (company + year range)
        Executive Overview (narrative in a styled box)
        Income Statement table  (with YoY % column)
        Balance Sheet table
        Financial Quality table (margins %, ratio, Piotroski score)
        Risk Flags box

    Performs ZERO computation. All values come from the supplied dicts.
    Missing values display as "N/A". All user-supplied text is HTML-escaped.
    """
    company = summary.get("company", "")
    years   = summary.get("years", [])
    income  = summary.get("income_statement", {})
    balance = summary.get("balance_sheet", {})
    quality = summary.get("quality_metrics", {})

    if len(years) >= 2:
        year_range = f"{years[0]}&ndash;{years[-1]}"
    elif years:
        year_range = str(years[0])
    else:
        year_range = "N/A"

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        f"<title>{_e(company)} Financial Report</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        # ── Title ──────────────────────────────────────────────────────────
        f'<div class="report-title">{_e(company)}</div>',
        f'<p class="report-subtitle">Financial Report &mdash; {year_range}</p>',
        '<hr class="divider">',
        # ── Executive Overview ─────────────────────────────────────────────
        '<div class="section-header">Executive Overview</div>',
        f'<div class="narrative-box">{_e(narrative)}</div>',
        # ── Income Statement ───────────────────────────────────────────────
        '<div class="section-header">Income Statement</div>',
        _income_table(income, years),
        # ── Balance Sheet ──────────────────────────────────────────────────
        '<div class="section-header">Balance Sheet</div>',
        _balance_table(balance, years),
        # ── Financial Quality ──────────────────────────────────────────────
        '<div class="section-header">Financial Quality</div>',
        _quality_table(quality, years),
        _risk_section(quality, years),
        # ── Footer ────────────────────────────────────────────────────────
        '<div class="footer">Generated by ACE Research Financial Reporter</div>',
        "</body>",
        "</html>",
    ]

    return "\n".join(parts)


# =============================================================================
# Part 2 — PDF Generator
# =============================================================================

def generate_pdf(summary: dict, narrative: str, output_path: str) -> None:
    """
    Generate a PDF financial report and write it to output_path.

    Calls render_html_report() then converts the result to PDF via WeasyPrint.
    Raises ImportError if WeasyPrint is not installed.

    No printing. No formatting logic outside render_html_report().
    """
    if not _WEASYPRINT_AVAILABLE:
        raise ImportError(
            "WeasyPrint is required for PDF generation. "
            "Install it with: pip install weasyprint"
        )
    html = render_html_report(summary, narrative)
    _WeasyHTML(string=html).write_pdf(output_path)
