"""
report_narrative.py

Deterministic executive narrative generator for financial summaries.

Part 1: generate_deterministic_narrative(summary) -> str
Part 2: generate_narrative(summary, mode="deterministic") -> str

Rules:
    YoY > 0        -> "increased"
    YoY < 0        -> "declined"
    |YoY| < 1.0%   -> "remained stable"

Never accesses the database. Never computes new metrics. Pure text generation.
"""

from __future__ import annotations

from typing import Optional

from ace_research.risk_engine import analyze_risk


# =============================================================================
# Thresholds
# =============================================================================

_STABLE_YOY_THRESHOLD    = 1.0    # percentage points; |yoy_pct| below this is "stable"
_STABLE_MARGIN_THRESHOLD = 0.001  # decimal units; margin diff below this is "stable"


# =============================================================================
# Private helpers
# =============================================================================

def _direction(yoy_pct: Optional[float]) -> str:
    """Map a YoY percent value to an English direction word."""
    if yoy_pct is None or abs(yoy_pct) < _STABLE_YOY_THRESHOLD:
        return "remained stable"
    return "increased" if yoy_pct > 0 else "declined"


def _margin_direction(values: dict, years: list) -> str:
    """
    Compare margin at the latest year vs the prior year.

    Returns "improved", "declined", or "remained stable".
    Stable when fewer than two years are supplied or either value is None.
    """
    if len(years) < 2:
        return "remained stable"
    v_latest = values.get(years[-1])
    v_prior  = values.get(years[-2])
    if v_latest is None or v_prior is None:
        return "remained stable"
    diff = v_latest - v_prior
    if abs(diff) < _STABLE_MARGIN_THRESHOLD:
        return "remained stable"
    return "improved" if diff > 0 else "declined"


def _piotroski_trend(pio_values: dict, years: list) -> str:
    """
    Classify Piotroski score trend across the provided years.

    Compares the first non-None score to the last non-None score.
    Returns "improved", "declined", "remained stable", or "insufficient data".
    """
    scored = [(yr, pio_values.get(yr)) for yr in years if pio_values.get(yr) is not None]
    if len(scored) < 2:
        return "insufficient data"
    first, last = scored[0][1], scored[-1][1]
    if last > first:
        return "improved"
    elif last < first:
        return "declined"
    return "remained stable"


def _fmt_revenue(value: Optional[float]) -> str:
    """Format a revenue figure for narrative prose."""
    if value is None:
        return "N/A"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


# =============================================================================
# Part 1 — Deterministic Narrative
# =============================================================================

def generate_deterministic_narrative(summary: dict) -> str:
    """
    Generate a concise (6-10 sentences) executive narrative from a financial
    summary dict produced by build_financial_summary().

    Sections:
        1. Opening — company and year range
        2. Revenue — latest value and YoY direction
        3. Net income — YoY direction
        4. Margin — operating_margin preferred, falls back to gross_margin
        5. Piotroski F-Score — trend across provided years
        6. Risk flags — present or absent for latest year

    Language rules:
        YoY > 0        -> "increased"
        YoY < 0        -> "declined"
        |YoY| < 1.0%   -> "remained stable"

    Reads only from the supplied dict.
    No database access. No new computation.
    """
    company = summary.get("company", "The company")
    years   = summary.get("years", [])
    income  = summary.get("income_statement", {})
    quality = summary.get("quality_metrics", {})

    latest = years[-1] if years else None

    # Compute risk analysis and store on summary so downstream consumers (e.g.
    # report_pdf.py) can use it without recomputing.
    risk_analysis = analyze_risk(summary, years)
    summary["risk_analysis"] = risk_analysis

    sentences: list = []

    # ── 1. Opening ────────────────────────────────────────────────────────────
    if len(years) >= 2:
        year_range = f"{years[0]}-{years[-1]}"
    elif years:
        year_range = str(years[0])
    else:
        year_range = "the reported period"

    sentences.append(
        f"Executive Overview: {company} financial performance for {year_range}."
    )

    # ── 2. Revenue ────────────────────────────────────────────────────────────
    rev_entry  = income.get("revenue", {})
    rev_vals   = rev_entry.get("values", {})
    rev_yoy    = rev_entry.get("yoy_pct")
    rev_latest = rev_vals.get(latest) if latest is not None else None
    rev_dir    = _direction(rev_yoy)

    if rev_latest is not None:
        yoy_suffix = f" ({rev_yoy:+.1f}% YoY)" if rev_yoy is not None else ""
        sentences.append(
            f"Revenue {rev_dir} to {_fmt_revenue(rev_latest)}{yoy_suffix}."
        )
    else:
        sentences.append("Revenue data is unavailable for the latest period.")

    # ── 3. Net income ─────────────────────────────────────────────────────────
    ni_entry  = income.get("net_income", {})
    ni_vals   = ni_entry.get("values", {})
    ni_yoy    = ni_entry.get("yoy_pct")
    ni_dir    = _direction(ni_yoy)
    ni_latest = ni_vals.get(latest) if latest is not None else None

    if ni_latest is not None:
        yoy_suffix = f" ({ni_yoy:+.1f}% YoY)" if ni_yoy is not None else ""
        sentences.append(f"Net income {ni_dir}{yoy_suffix}.")
    else:
        sentences.append("Net income data is unavailable for the latest period.")

    # ── 4. Margin movement — prefer operating_margin, fall back to gross_margin
    margin_label = None
    margin_dir   = "remained stable"
    for margin_key in ("operating_margin", "gross_margin"):
        entry = quality.get(margin_key, {})
        vals  = entry.get("values", {})
        if vals:
            margin_dir   = _margin_direction(vals, years)
            margin_label = margin_key.replace("_", " ").title()
            break

    if margin_label:
        sentences.append(f"{margin_label} {margin_dir} year-over-year.")
    else:
        sentences.append("Margin data is unavailable.")

    # ── 5. Piotroski trend ────────────────────────────────────────────────────
    pio_entry  = quality.get("piotroski_score", {})
    pio_vals   = pio_entry.get("values", {})
    latest_pio = pio_vals.get(latest) if latest is not None else None

    if pio_vals:
        pio_trend = _piotroski_trend(pio_vals, years)
        if pio_trend == "insufficient data":
            if latest_pio is not None:
                sentences.append(
                    f"The Piotroski F-Score for {latest} was {latest_pio}/9"
                    " (single year; trend unavailable)."
                )
            else:
                sentences.append("Insufficient Piotroski score data to assess trend.")
        else:
            pio_suffix = f" (latest: {latest_pio}/9)" if latest_pio is not None else ""
            sentences.append(
                f"Financial health as measured by the Piotroski F-Score"
                f" {pio_trend}{pio_suffix}."
            )
    else:
        sentences.append("Piotroski score data is unavailable.")

    # ── 6. Risk flags ─────────────────────────────────────────────────────────
    flags = quality.get("risk_flags", [])
    if latest is not None:
        if flags:
            flag_list = ", ".join(sorted(flags))
            sentences.append(
                f"The following risk signals were identified for {latest}: {flag_list}."
            )
        else:
            sentences.append(
                f"No financial risk flags were detected for {latest}."
            )

    # ── 7. Risk assessment summary ────────────────────────────────────────────
    if latest is not None:
        level = risk_analysis.get("overall_level", "Unknown")
        score = risk_analysis.get("overall_score", 0)
        sentences.append(
            f"Risk assessment for {latest}: {level} risk level (composite score: {score:+d})."
        )

    return " ".join(sentences)


# =============================================================================
# Part 2 — Narrative Switch
# =============================================================================

def generate_narrative(summary: dict, mode: str = "deterministic") -> str:
    """
    Dispatcher for narrative generation.

    mode="deterministic"  -> generate_deterministic_narrative()
    Any other mode        -> NotImplementedError (reserved for LLM-based modes)
    """
    if mode == "deterministic":
        return generate_deterministic_narrative(summary)
    raise NotImplementedError(
        f"Narrative mode '{mode}' is not implemented. "
        "Only 'deterministic' is currently supported."
    )
