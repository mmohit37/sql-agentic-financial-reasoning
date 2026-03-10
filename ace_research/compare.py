"""
compare.py

Multi-company financial comparison for the ACE Research reporting system.

Public API:
    compare_companies(companies, year) -> list[dict]
        Returns one row dict per company with key metrics for the given year.

CLI:
    python -m ace_research.compare --companies Microsoft Apple Nvidia --year 2023
    python -m ace_research.compare --companies Microsoft Apple --year 2023 --pdf out.pdf
"""

from __future__ import annotations

from typing import Optional


# =============================================================================
# Core comparison logic
# =============================================================================

def compare_companies(companies: list[str], year: int) -> list[dict]:
    """
    Compare financial metrics across multiple companies for a given year.

    For each company:
      1. Ensures filings are present via ensure_company_years_ready.
      2. Builds the full financial summary via build_financial_summary.
      3. Runs the risk engine to populate risk_analysis.
      4. Extracts year-specific metrics into a flat row dict.

    Parameters
    ----------
    companies : list[str]
        Company names as they appear in the database / SEC registry.
    year : int
        The fiscal year to compare.

    Returns
    -------
    list[dict]
        Each dict has keys:
            company, revenue, net_margin, return_on_equity, debt_ratio, risk_level
        Missing values are None; risk_level is "N/A" when risk analysis is absent.
    """
    from ace_research.orchestration import ensure_company_years_ready
    from ace_research.report import build_financial_summary
    from ace_research.risk_engine import analyze_risk

    rows = []
    for company in companies:
        try:
            ensure_company_years_ready(company, [year])
            summary = build_financial_summary(company, [year])
            risk    = analyze_risk(summary, [year])
            summary["risk_analysis"] = risk
        except Exception:
            # Company unavailable or data missing — emit a sparse row
            rows.append({
                "company":          company,
                "revenue":          None,
                "net_margin":       None,
                "return_on_equity": None,
                "debt_ratio":       None,
                "risk_level":       "N/A",
            })
            continue

        qm      = summary.get("quality_metrics", {})
        income  = summary.get("income_statement", {})

        rows.append({
            "company":          company,
            "revenue":          income.get("revenue", {}).get("values", {}).get(year),
            "net_margin":       qm.get("net_margin",       {}).get("values", {}).get(year),
            "return_on_equity": qm.get("return_on_equity", {}).get("values", {}).get(year),
            "debt_ratio":       qm.get("debt_ratio",       {}).get("values", {}).get(year),
            "risk_level":       risk.get("overall_level", "N/A"),
        })

    return rows


# =============================================================================
# Format helpers (console)
# =============================================================================

def _fmt_num(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    abs_v = abs(v)
    if abs_v >= 1_000_000_000:
        s = f"{v / 1_000_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}B"
    if abs_v >= 1_000_000:
        s = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if abs_v >= 1_000:
        return f"{v:,.0f}"
    return f"{v:.2f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    s = f"{v * 100:.1f}".rstrip("0").rstrip(".")
    return f"{s}%"


# =============================================================================
# Console renderer
# =============================================================================

_COL_COMPANY = 16
_COL_METRIC  = 12

def render_comparison_cli(rows: list[dict], year: int) -> None:
    """Print a formatted comparison table to stdout."""
    headers = ["Company", "Revenue", "Net Margin", "ROE", "Debt Ratio", "Risk Level"]
    widths  = [_COL_COMPANY, _COL_METRIC, _COL_METRIC, _COL_METRIC, _COL_METRIC, _COL_METRIC]

    def _row(cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    separator = "-" * sum(w + 2 for w in widths)

    print(f"\nCompany Comparison — FY {year}")
    print(separator)
    print(_row(headers))
    print(separator)
    for r in rows:
        print(_row([
            r["company"],
            _fmt_num(r["revenue"]),
            _fmt_pct(r["net_margin"]),
            _fmt_pct(r["return_on_equity"]),
            _fmt_pct(r["debt_ratio"]),
            r["risk_level"] or "N/A",
        ]))
    print(separator)


# =============================================================================
# PDF renderer (optional)
# =============================================================================

def generate_comparison_pdf(rows: list[dict], year: int, output_path: str) -> None:
    """
    Write a comparison table PDF to output_path.

    Raises ImportError if ReportLab is not installed.
    """
    try:
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        )
        from reportlab.lib import colors, pagesizes
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
    except ImportError:
        raise ImportError(
            "ReportLab is required for PDF generation. "
            "Install with: pip install reportlab"
        )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=pagesizes.LETTER,
        leftMargin=inch, rightMargin=inch,
        topMargin=inch,  bottomMargin=inch,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CompTitle",
        parent=styles["Heading1"],
        fontSize=18, leading=22, spaceAfter=4,
        textColor=colors.HexColor("#1a3a6e"),
    )
    subtitle_style = ParagraphStyle(
        "CompSubtitle",
        parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#666666"), spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "CompSection",
        parent=styles["Heading2"],
        fontSize=12, leading=16, spaceBefore=10, spaceAfter=6,
        textColor=colors.HexColor("#1a3a6e"),
        borderPad=2,
    )
    footer_style = ParagraphStyle(
        "CompFooter",
        parent=styles["Normal"],
        fontSize=7, textColor=colors.HexColor("#aaaaaa"), alignment=1,
    )

    # ── Table data ─────────────────────────────────────────────────────────────
    header = ["Company", "Revenue", "Net Margin", "ROE", "Debt Ratio", "Risk Level"]
    data   = [header]
    for r in rows:
        data.append([
            r["company"],
            _fmt_num(r["revenue"]),
            _fmt_pct(r["net_margin"]),
            _fmt_pct(r["return_on_equity"]),
            _fmt_pct(r["debt_ratio"]),
            r["risk_level"] or "N/A",
        ])

    available = 6.5 * inch
    col_w     = available / len(header)
    col_widths = [col_w] * len(header)

    n_rows = len(data)
    table_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf8")),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 10),
        ("LINEBELOW",  (0, 0), (-1, 0), 1.5, colors.HexColor("#8a9dbf")),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 9),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ef")),
        ("ALIGN",      (0, 0), (0, -1),  "LEFT"),
        ("ALIGN",      (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]
    # Alternate row shading
    for i in range(2, n_rows, 2):
        table_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f4f6fb")))

    comp_table = Table(data, colWidths=col_widths, repeatRows=1)
    comp_table.setStyle(TableStyle(table_cmds))

    story = [
        Paragraph(f"Multi-Company Comparison — FY {year}", title_style),
        Paragraph(
            f"Companies: {', '.join(r['company'] for r in rows)}",
            subtitle_style,
        ),
        Paragraph("Financial Comparison", section_style),
        comp_table,
        Spacer(1, 0.3 * inch),
        Paragraph("Generated by ACE Research Financial Reporter", footer_style),
    ]

    doc.build(story)


# =============================================================================
# CLI entry point
# =============================================================================

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare financial metrics across multiple companies for a given year."
    )
    parser.add_argument(
        "--companies", required=True, nargs="+", metavar="COMPANY",
        help="One or more company names (e.g. Microsoft Apple Nvidia)",
    )
    parser.add_argument(
        "--year", required=True, type=int, metavar="YEAR",
        help="Fiscal year to compare (e.g. 2023)",
    )
    parser.add_argument(
        "--pdf", default=None, metavar="OUTPUT_PATH",
        help="Optional: write comparison PDF to OUTPUT_PATH",
    )
    args = parser.parse_args()

    rows = compare_companies(args.companies, args.year)
    render_comparison_cli(rows, args.year)

    if args.pdf:
        generate_comparison_pdf(rows, args.year, args.pdf)
        print(f"PDF saved to: {args.pdf}")


if __name__ == "__main__":
    _main()
