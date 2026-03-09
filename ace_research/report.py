"""
report.py

Deterministic financial summary table generator.

Strict two-component separation:
  build_financial_summary()      -- JSON builder: pure data retrieval + YoY computation
  render_financial_summary_cli() -- CLI renderer: pure formatting, zero computation

CLI:
    python -m ace_research.report --company Microsoft --years 2021 2022 2023
"""

from __future__ import annotations

import argparse
from typing import Optional

from ace_research.db import get_canonical_financial_fact, get_metric_ratio
from ace_research.experiments import get_piotroski_from_db, build_risk_flags
from ace_research.orchestration import ensure_company_years_ready


# =============================================================================
# Shared constants
# =============================================================================

_INCOME_METRICS = ["revenue", "operating_income", "net_income"]
_BALANCE_METRICS = ["total_assets", "total_liabilities", "total_equity"]

# Each derived metric: name -> (numerator canonical metric, denominator canonical metric)
_DERIVED_METRIC_SPECS: dict[str, tuple[str, str]] = {
    "gross_margin":     ("gross_profit",      "revenue"),
    "operating_margin": ("operating_income",  "revenue"),
    "net_margin":       ("net_income",        "revenue"),
    "current_ratio":    ("current_assets",    "current_liabilities"),
    # Extended derived metrics (Phase B)
    "asset_turnover":   ("revenue",           "total_assets"),
    "return_on_assets": ("net_income",        "total_assets"),
    "return_on_equity": ("net_income",        "total_equity"),
    "debt_ratio":       ("total_liabilities", "total_assets"),
    "quick_ratio":      ("current_assets",    "current_liabilities"),
}

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
    "piotroski_score":   "Piotroski Score",
    # Extended metrics (Phase B)
    "asset_turnover":    "Asset Turnover",
    "return_on_assets":  "Return on Assets",
    "return_on_equity":  "Return on Equity",
    "debt_ratio":        "Debt Ratio",
    "quick_ratio":       "Quick Ratio",
}

# Renderer column widths
_COL_LABEL = 22   # total width of label column (includes 2-space indent)
_COL_VALUE = 14   # width of each year value column
_COL_YOY   = 10   # width of YoY % column (income statement only)


# =============================================================================
# Part 1 — JSON Builder
# =============================================================================

def _yoy_pct(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    """
    YoY percent change: (current - prior) / |prior| * 100.
    Returns None when either value is missing or prior is zero.
    Uses abs(prior) so sign of change reflects direction of movement
    even when prior is negative (e.g. a loss turning to profit).
    """
    if current is None or prior is None or prior == 0:
        return None
    return round((current - prior) / abs(prior) * 100, 2)


def build_financial_summary(company: str, years: list[int]) -> dict:
    """
    Build a structured financial summary for a company across given years.

    Data sources (all existing helpers, no new computation beyond YoY %):
      - get_canonical_financial_fact()  for income statement and balance sheet
      - get_metric_ratio()              for derived quality metrics
      - get_piotroski_from_db()         for Piotroski score per year
      - build_risk_flags()              for risk flags of the latest year

    YoY percent change is computed only for income statement metrics
    (latest year vs the year immediately before it in the supplied list).

    Does NOT print or format anything. Returns pure structured data.

    Return shape:
    {
        "company": str,
        "years":   [int, ...],          # sorted ascending

        "income_statement": {
            "<metric>": {
                "values":  {year: float | None, ...},
                "yoy_pct": float | None,   # latest vs prior only
            }, ...
        },

        "balance_sheet": {
            "<metric>": {
                "values": {year: float | None, ...},
            }, ...
        },

        "quality_metrics": {
            "<metric>": {
                "values": {year: float | None, ...},
            }, ...
            "piotroski_score": {
                "values": {year: int | None, ...},
            },
            "risk_flags": [str, ...],    # latest year only
        }
    }
    """
    ensure_company_years_ready(company, years)

    years = sorted(years)
    latest = years[-1] if years else None
    prior  = years[-2] if len(years) >= 2 else None

    # ── Income Statement ─────────────────────────────────────────────────────
    income_statement: dict = {}
    for metric in _INCOME_METRICS:
        values = {yr: get_canonical_financial_fact(metric, yr, company) for yr in years}
        yoy = (
            _yoy_pct(values.get(latest), values.get(prior))
            if prior is not None
            else None
        )
        income_statement[metric] = {"values": values, "yoy_pct": yoy}

    # ── Balance Sheet ─────────────────────────────────────────────────────────
    balance_sheet: dict = {}
    for metric in _BALANCE_METRICS:
        values = {yr: get_canonical_financial_fact(metric, yr, company) for yr in years}
        balance_sheet[metric] = {"values": values}

    # ── Derived Quality Metrics ───────────────────────────────────────────────
    quality_metrics: dict = {}
    for name, (num, den) in _DERIVED_METRIC_SPECS.items():
        values = {yr: get_metric_ratio(num, den, yr, company) for yr in years}
        quality_metrics[name] = {"values": values}

    # ── Piotroski Score per year ──────────────────────────────────────────────
    piotroski_values: dict = {}
    for yr in years:
        result = get_piotroski_from_db(company, yr)
        piotroski_values[yr] = result.get("total_score")
    quality_metrics["piotroski_score"] = {"values": piotroski_values}

    # ── Risk Flags (latest year only) ─────────────────────────────────────────
    if latest is not None:
        risk_result = build_risk_flags(company, latest)
        quality_metrics["risk_flags"] = risk_result["risk_flags"]
    else:
        quality_metrics["risk_flags"] = []

    # --- Derived Metric Fallbacks ---
    # Summary-layer only. DB is never mutated. Explicit values are never overridden.
    for yr in years:
        rev     = income_statement["revenue"]["values"].get(yr)
        net_inc = income_statement["net_income"]["values"].get(yr)
        assets  = balance_sheet["total_assets"]["values"].get(yr)
        liabs   = balance_sheet["total_liabilities"]["values"].get(yr)

        # 1) Gross Profit: revenue - cost_of_revenue when gross_profit is absent
        gp = get_canonical_financial_fact("gross_profit", yr, company)
        if gp is None and rev is not None:
            cor = get_canonical_financial_fact("cost_of_revenue", yr, company)
            if cor is not None:
                gp = rev - cor

        # 2) Gross Margin: gross_profit / revenue (explicit or derived above)
        if quality_metrics["gross_margin"]["values"].get(yr) is None:
            if gp is not None and rev:
                quality_metrics["gross_margin"]["values"][yr] = gp / rev

        # 3) Total Equity: assets - liabilities when not directly reported
        if balance_sheet["total_equity"]["values"].get(yr) is None:
            if assets is not None and liabs is not None:
                balance_sheet["total_equity"]["values"][yr] = assets - liabs

        # 4) Net Margin: net_income / revenue when not already in quality metrics
        if quality_metrics["net_margin"]["values"].get(yr) is None:
            if net_inc is not None and rev:
                quality_metrics["net_margin"]["values"][yr] = net_inc / rev

        # Read equity after potential derivation in step 3
        equity = balance_sheet["total_equity"]["values"].get(yr)

        # 5) Asset Turnover: revenue / total_assets
        if quality_metrics["asset_turnover"]["values"].get(yr) is None:
            if rev is not None and assets:
                quality_metrics["asset_turnover"]["values"][yr] = rev / assets

        # 6) Return on Assets (ROA): net_income / total_assets
        if quality_metrics["return_on_assets"]["values"].get(yr) is None:
            if net_inc is not None and assets:
                quality_metrics["return_on_assets"]["values"][yr] = net_inc / assets

        # 7) Return on Equity (ROE): net_income / total_equity
        if quality_metrics["return_on_equity"]["values"].get(yr) is None:
            if net_inc is not None and equity:
                quality_metrics["return_on_equity"]["values"][yr] = net_inc / equity

        # 8) Debt Ratio: total_liabilities / total_assets
        if quality_metrics["debt_ratio"]["values"].get(yr) is None:
            if liabs is not None and assets:
                quality_metrics["debt_ratio"]["values"][yr] = liabs / assets

        # 9) Quick Ratio: (current_assets - inventory) / current_liabilities
        #    Falls back to current_assets / current_liabilities when inventory absent.
        if quality_metrics["quick_ratio"]["values"].get(yr) is None:
            cur_a = get_canonical_financial_fact("current_assets", yr, company)
            cur_l = get_canonical_financial_fact("current_liabilities", yr, company)
            if cur_a is not None and cur_l:
                inv = get_canonical_financial_fact("inventory", yr, company)
                liquid_assets = cur_a - inv if inv is not None else cur_a
                quality_metrics["quick_ratio"]["values"][yr] = liquid_assets / cur_l

    return {
        "company":           company,
        "years":             years,
        "income_statement":  income_statement,
        "balance_sheet":     balance_sheet,
        "quality_metrics":   quality_metrics,
    }


# =============================================================================
# Part 2 — CLI Renderer
# =============================================================================

def _fmt_num(value: Optional[float]) -> str:
    """Large absolute number with thousands separator; small values to 2dp; None → 'N/A'."""
    if value is None:
        return "N/A"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    """Decimal ratio → percentage string (0.25 → '25.00%'); None → 'N/A'."""
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_ratio(value: Optional[float]) -> str:
    """Pure decimal ratio to 4 decimal places; None → 'N/A'."""
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _fmt_yoy(value: Optional[float]) -> str:
    """YoY percent with explicit sign (+/-); None → 'N/A'."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fmt_score(value) -> str:
    """Integer Piotroski score; None → 'N/A'."""
    return str(value) if value is not None else "N/A"


def _col_header(years: list[int], include_yoy: bool = False) -> str:
    """Build the column header row (blank label column + year columns + optional YoY)."""
    row = " " * _COL_LABEL
    for yr in years:
        row += f"{yr:>{_COL_VALUE}}"
    if include_yoy:
        row += f"{'YoY %':>{_COL_YOY}}"
    return row


def render_financial_summary_cli(summary: dict) -> None:
    """
    Render a financial summary dict to stdout.

    Performs ZERO computation. Every displayed value is read directly from the
    input dict produced by build_financial_summary(). No arithmetic here.

    Sections printed:
        INCOME STATEMENT  — with YoY % column for latest year
        BALANCE SHEET     — no YoY column
        FINANCIAL QUALITY — ratios, Piotroski score, risk flags
    """
    company = summary["company"]
    years   = summary["years"]
    income  = summary["income_statement"]
    balance = summary["balance_sheet"]
    quality = summary["quality_metrics"]
    latest  = years[-1] if years else None
    flags   = quality.get("risk_flags", [])

    sep_width = _COL_LABEL + _COL_VALUE * len(years) + _COL_YOY + 4
    sep = "=" * max(sep_width, 60)

    print()
    print(f"Financial Summary: {company} ({', '.join(str(y) for y in years)})")
    print(sep)

    # ── Income Statement ──────────────────────────────────────────────────────
    print()
    print("INCOME STATEMENT")
    print(_col_header(years, include_yoy=True))
    for metric in _INCOME_METRICS:
        entry = income.get(metric, {})
        vals  = entry.get("values", {})
        yoy   = entry.get("yoy_pct")
        label = _METRIC_LABELS.get(metric, metric)
        row   = f"  {label:{_COL_LABEL - 2}}"
        for yr in years:
            row += f"{_fmt_num(vals.get(yr)):>{_COL_VALUE}}"
        row += f"{_fmt_yoy(yoy):>{_COL_YOY}}"
        print(row)

    # ── Balance Sheet ─────────────────────────────────────────────────────────
    print()
    print("BALANCE SHEET")
    print(_col_header(years))
    for metric in _BALANCE_METRICS:
        entry = balance.get(metric, {})
        vals  = entry.get("values", {})
        label = _METRIC_LABELS.get(metric, metric)
        row   = f"  {label:{_COL_LABEL - 2}}"
        for yr in years:
            row += f"{_fmt_num(vals.get(yr)):>{_COL_VALUE}}"
        print(row)

    # ── Financial Quality ─────────────────────────────────────────────────────
    print()
    print("FINANCIAL QUALITY")
    print(_col_header(years))

    # Margin ratios (displayed as %)
    for metric in ("gross_margin", "operating_margin", "net_margin"):
        entry = quality.get(metric, {})
        vals  = entry.get("values", {})
        label = _METRIC_LABELS.get(metric, metric)
        row   = f"  {label:{_COL_LABEL - 2}}"
        for yr in years:
            row += f"{_fmt_pct(vals.get(yr)):>{_COL_VALUE}}"
        print(row)

    # Current ratio (plain decimal)
    cr_entry = quality.get("current_ratio", {})
    cr_vals  = cr_entry.get("values", {})
    row = f"  {'Current Ratio':{_COL_LABEL - 2}}"
    for yr in years:
        row += f"{_fmt_ratio(cr_vals.get(yr)):>{_COL_VALUE}}"
    print(row)

    # Piotroski score
    pio_entry = quality.get("piotroski_score", {})
    pio_vals  = pio_entry.get("values", {})
    row = f"  {'Piotroski Score':{_COL_LABEL - 2}}"
    for yr in years:
        row += f"{_fmt_score(pio_vals.get(yr)):>{_COL_VALUE}}"
    print(row)

    # Risk flags
    print()
    if latest is not None:
        if flags:
            print(f"Risk Flags ({latest}): {', '.join(sorted(flags))}")
        else:
            print(f"Risk Flags ({latest}): None detected.")
    print()


# =============================================================================
# Part 3 — CLI Entrypoint
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a deterministic financial summary table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: python -m ace_research.report --company Microsoft --years 2021 2022 2023",
    )
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument(
        "--years", required=True, nargs="+", type=int, metavar="YEAR",
        help="One or more fiscal years (e.g. 2021 2022 2023)",
    )
    parser.add_argument(
        "--pdf", default=None, metavar="OUTPUT_PATH",
        help="Optional: generate a PDF report and save to OUTPUT_PATH",
    )
    parser.add_argument(
        "--narrative",
        choices=["deterministic", "llm"],
        default="deterministic",
        metavar="MODE",
        help=(
            "Narrative generation mode for PDF output: "
            "'deterministic' (default, no API key required) or "
            "'llm' (calls Anthropic API; falls back to deterministic on failure)."
        ),
    )
    args = parser.parse_args()

    summary = build_financial_summary(args.company, args.years)
    render_financial_summary_cli(summary)

    if args.pdf:
        from ace_research.report_narrative import generate_narrative
        from ace_research.report_pdf import generate_pdf

        # Always build deterministic narrative first (also populates risk_analysis).
        narrative = generate_narrative(summary, mode="deterministic")

        if args.narrative == "llm":
            try:
                from ace_research.narrative_llm import generate_llm_summary
                narrative = generate_llm_summary(summary, args.years)
                print("[INFO] LLM narrative generated successfully.")
            except Exception as exc:
                print(
                    f"[WARNING] LLM narrative failed ({type(exc).__name__}: {exc}); "
                    "falling back to deterministic narrative."
                )

        generate_pdf(summary, narrative, args.pdf)
        print(f"PDF saved to: {args.pdf}")
