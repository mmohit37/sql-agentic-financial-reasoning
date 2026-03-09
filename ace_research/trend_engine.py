"""
trend_engine.py

Detects multi-year financial trends from a pre-computed summary dict and
returns a list of plain-English signal strings.

Public API:
    analyze_trends(summary, years) -> dict
        Returns {"signals": [str]}.
        Reads ONLY from summary dict. No database access. Deterministic.
"""

from __future__ import annotations

from typing import Optional


def _first_last(values: dict, years: list[int]) -> tuple[Optional[float], Optional[float]]:
    """Return the first and last non-None values across the ordered years list."""
    first = last = None
    for yr in years:
        v = values.get(yr)
        if v is not None:
            if first is None:
                first = v
            last = v
    return first, last


def _revenue_cagr_signal(summary: dict, years: list[int]) -> Optional[str]:
    rev_values = (
        summary.get("income_statement", {})
               .get("revenue", {})
               .get("values", {})
    )
    first, last = _first_last(rev_values, years)
    if first is None or last is None or first == 0:
        return None
    # Find how many periods span from first non-None to last non-None year
    non_none_years = [yr for yr in years if rev_values.get(yr) is not None]
    n_periods = len(non_none_years) - 1
    if n_periods < 1:
        return None
    cagr = (last / first) ** (1.0 / n_periods) - 1.0
    sign = "+" if cagr >= 0 else ""
    formatted = f"{sign}{cagr * 100:.1f}".rstrip("0").rstrip(".")
    return f"Revenue CAGR: {formatted}% over the analyzed period"


def _margin_signal(summary: dict, years: list[int]) -> Optional[str]:
    margin_values = (
        summary.get("quality_metrics", {})
               .get("net_margin", {})
               .get("values", {})
    )
    first, last = _first_last(margin_values, years)
    if first is None or last is None:
        return None
    if last < first - 0.02:
        return "Net margin compression detected"
    if last > first + 0.02:
        return "Net margin expansion detected"
    return None


def _leverage_signal(summary: dict, years: list[int]) -> Optional[str]:
    debt_values = (
        summary.get("quality_metrics", {})
               .get("debt_ratio", {})
               .get("values", {})
    )
    first, last = _first_last(debt_values, years)
    if first is None or last is None:
        return None
    if last < first:
        return "Leverage improving (debt ratio declining)"
    if last > first:
        return "Leverage increasing"
    return None


def _liquidity_signal(summary: dict, years: list[int]) -> Optional[str]:
    cr_values = (
        summary.get("quality_metrics", {})
               .get("current_ratio", {})
               .get("values", {})
    )
    first, last = _first_last(cr_values, years)
    if first is None or last is None:
        return None
    if last < first:
        return "Liquidity weakening"
    if last > first:
        return "Liquidity strengthening"
    return None


def analyze_trends(summary: dict, years: list[int]) -> dict:
    """
    Analyze multi-year financial trends from a pre-computed summary dict.

    Parameters
    ----------
    summary : dict
        Output of build_financial_summary().
    years : list[int]
        Sorted list of fiscal years.

    Returns
    -------
    dict
        {"signals": [str]} — list of plain-English trend signal strings.
        Empty when data is insufficient to produce a signal.
    """
    _signal_fns = [
        _revenue_cagr_signal,
        _margin_signal,
        _leverage_signal,
        _liquidity_signal,
    ]
    signals = [s for fn in _signal_fns if (s := fn(summary, years)) is not None]
    return {"signals": signals}
