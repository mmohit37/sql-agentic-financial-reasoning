"""
risk_engine.py

Severity-weighted financial risk analysis.

analyze_risk(summary, years) -> dict

Reads only from the summary dict produced by build_financial_summary().
No database access. No writes. Deterministic.
"""

from __future__ import annotations

from typing import Optional


# =============================================================================
# Severity / level helpers
# =============================================================================

def _severity(score: int) -> str:
    if score >= 1:
        return "positive"
    if score == 0:
        return "stable"
    if score == -1:
        return "moderate"
    return "elevated"


def _overall_level(total: int) -> str:
    if total <= -4:
        return "Elevated"
    if total <= -1:
        return "Moderate"
    if total <= 2:
        return "Low"
    return "Strong"


def _yoy_frac(values: dict, latest: int, years: list[int]) -> Optional[float]:
    """Fractional YoY change (e.g. 0.10 for +10%). None when unavailable."""
    idx = years.index(latest)
    if idx == 0:
        return None
    prior = years[idx - 1]
    v_now = values.get(latest)
    v_pri = values.get(prior)
    if v_now is None or v_pri is None or v_pri == 0:
        return None
    return (v_now - v_pri) / abs(v_pri)


# =============================================================================
# Category scorers — each returns (score: int, details: str)
# =============================================================================

def _score_liquidity(summary: dict, latest: int, years: list[int]) -> tuple[int, str]:
    cr_vals = (
        summary.get("quality_metrics", {})
               .get("current_ratio", {})
               .get("values", {})
    )
    cr = cr_vals.get(latest)

    if cr is None:
        return 0, "No current ratio data available."

    parts: list[str] = []
    score = 0

    # Base score from absolute CR level
    if cr < 1.0:
        score = -2
        parts.append(f"Current ratio {cr:.2f} is below 1.0 (elevated liquidity risk).")
    elif cr < 1.3:
        score = -1
        parts.append(f"Current ratio {cr:.2f} is below 1.3 (moderate liquidity risk).")
    else:
        parts.append(f"Current ratio {cr:.2f}.")

    # YoY adjustment
    chg = _yoy_frac(cr_vals, latest, years)
    if chg is not None:
        if chg < -0.15:
            score -= 1
            parts.append(f"Declined {chg * 100:.1f}% YoY.")
        elif chg > 0.15:
            score += 1
            parts.append(f"Improved {chg * 100:.1f}% YoY.")

    # High-CR bonus (stable CR above 2.5)
    if cr > 2.5 and (chg is None or chg >= -0.15):
        score += 1
        parts.append("Strong liquidity position (CR > 2.5, stable).")

    return score, " ".join(parts)


def _score_profitability(summary: dict, latest: int, years: list[int]) -> tuple[int, str]:
    nm_vals = (
        summary.get("quality_metrics", {})
               .get("net_margin", {})
               .get("values", {})
    )
    nm = nm_vals.get(latest)

    if nm is None:
        return 0, "No net margin data available."

    idx = years.index(latest)
    prior_nm = nm_vals.get(years[idx - 1]) if idx > 0 else None

    if prior_nm is None:
        return 0, f"Net margin {nm * 100:.1f}% (single year; no prior for comparison)."

    diff = nm - prior_nm          # decimal, e.g. -0.06 = -6 percentage-point drop
    score = 0
    parts: list[str] = []

    if diff < -0.05:
        score -= 2
        parts.append(f"Net margin dropped {diff * 100:.1f}pp YoY (severe).")
    elif diff < -0.02:
        score -= 1
        parts.append(f"Net margin dropped {diff * 100:.1f}pp YoY.")
    elif diff > 0.02:
        score += 1
        parts.append(f"Net margin improved {diff * 100:.1f}pp YoY.")
    else:
        parts.append(f"Net margin stable ({nm * 100:.1f}%).")

    # Extra -1 for two consecutive declines (needs ≥ 3 years)
    if idx >= 2 and diff < 0:
        nm_2prior = nm_vals.get(years[idx - 2])
        if nm_2prior is not None and prior_nm < nm_2prior:
            score -= 1
            parts.append("Two consecutive net margin declines.")

    return score, " ".join(parts)


def _score_revenue_stability(summary: dict, latest: int, years: list[int]) -> tuple[int, str]:
    rev_vals = (
        summary.get("income_statement", {})
               .get("revenue", {})
               .get("values", {})
    )
    if rev_vals.get(latest) is None:
        return 0, "No revenue data available."

    chg = _yoy_frac(rev_vals, latest, years)

    if chg is None:
        return 0, "Single year of revenue data."

    if chg < 0:
        # Check for second consecutive decline
        idx = years.index(latest)
        if idx >= 2:
            r_prior  = rev_vals.get(years[idx - 1])
            r_2prior = rev_vals.get(years[idx - 2])
            if r_prior is not None and r_2prior is not None and r_prior < r_2prior:
                return -2, (
                    f"Revenue declined {chg * 100:.1f}% YoY. Two consecutive revenue declines."
                )
        return -1, f"Revenue declined {chg * 100:.1f}% YoY."

    if chg > 0.15:
        return 1, f"Revenue grew {chg * 100:.1f}% YoY (strong)."

    return 0, f"Revenue grew {chg * 100:.1f}% YoY (moderate)."


def _score_leverage(summary: dict, latest: int, years: list[int]) -> tuple[int, str]:
    bs     = summary.get("balance_sheet", {})
    ld_vals = bs.get("long_term_debt",  {}).get("values", {})
    eq_vals = bs.get("total_equity",    {}).get("values", {})

    eq = eq_vals.get(latest)
    if eq is None:
        return 0, "No equity data available."

    if eq <= 0:
        return -2, f"Total equity is non-positive ({eq}); leverage risk is elevated."

    ld = ld_vals.get(latest)
    if ld is None:
        return 0, "No long-term debt data available."

    dte = ld / eq
    parts = [f"Debt-to-equity ratio {dte:.2f}."]
    score = 0

    idx = years.index(latest)
    if idx > 0:
        prior_yr = years[idx - 1]
        ld_prior = ld_vals.get(prior_yr)
        eq_prior = eq_vals.get(prior_yr)
        if ld_prior is not None and eq_prior is not None and eq_prior > 0:
            dte_prior = ld_prior / eq_prior
            if dte_prior != 0:
                chg = (dte - dte_prior) / abs(dte_prior)
                if chg > 0.20:
                    score = -1
                    parts.append(f"Debt-to-equity increased {chg * 100:.1f}% YoY.")
                elif chg < -0.20:
                    score = 1
                    parts.append(f"Debt-to-equity decreased {chg * 100:.1f}% YoY.")

    return score, " ".join(parts)


# =============================================================================
# Public API
# =============================================================================

def analyze_risk(summary: dict, years: list[int]) -> dict:
    """
    Compute a severity-weighted risk analysis from a financial summary dict.

    Args:
        summary: Output of build_financial_summary().
        years:   Sorted list of fiscal years covered.

    Returns:
        {
            "overall_score": int,
            "overall_level": str,         # "Elevated" | "Moderate" | "Low" | "Strong"
            "categories": [
                {
                    "name":     str,
                    "score":    int,
                    "severity": str,      # "elevated" | "moderate" | "stable" | "positive"
                    "details":  str,
                }
            ]
        }
    """
    if not years:
        return {"overall_score": 0, "overall_level": "Low", "categories": []}

    latest = years[-1]

    scorers = [
        ("Liquidity",         _score_liquidity),
        ("Profitability",     _score_profitability),
        ("Revenue Stability", _score_revenue_stability),
        ("Leverage",          _score_leverage),
    ]

    categories = []
    total = 0
    for name, fn in scorers:
        score, details = fn(summary, latest, years)
        total += score
        categories.append({
            "name":     name,
            "score":    score,
            "severity": _severity(score),
            "details":  details,
        })

    return {
        "overall_score": total,
        "overall_level": _overall_level(total),
        "categories":    categories,
    }
