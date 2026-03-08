"""
narrative_llm.py

LLM-powered executive narrative generator using the Anthropic API.

Reads ONLY from the pre-computed summary dict (output of build_financial_summary).
Never accesses the database. Never computes new metrics.

Public API:
    generate_llm_summary(summary, years) -> str
        Returns a 4-6 sentence executive summary of the company's financial condition.
        Raises on API failure; the caller must catch and fall back to deterministic.
"""

from __future__ import annotations

import os
from typing import Optional

import anthropic


# Model specified in requirements.
# NOTE: claude-3-sonnet-20240229 is retired; update to a current model
# (e.g. claude-opus-4-6) if API calls fail in production.
_MODEL       = "claude-sonnet-4-6"
_TEMPERATURE = 0.2
_MAX_TOKENS  = 300

_SYSTEM_PROMPT = """\
You are a financial analyst writing an executive overview of a company's financial condition.

Rules:
- Use ONLY the provided metrics. Do NOT invent or estimate any numbers not shown.
- Write clearly and professionally in plain English.
- Begin your response with "Executive Overview" on its own line.
- Then produce exactly 5 to 6 bullet points, each on its own line, starting with \u2022 (bullet character).
- Each bullet must be one concise sentence covering a single topic.
- Cover these topics across the bullets: revenue trend, profitability trend, \
liquidity, leverage, balance sheet strength, and overall risk level.
- Do NOT write paragraphs. Bullet points only. No additional markdown formatting.
"""


# =============================================================================
# Private helpers
# =============================================================================

def _fmt(value: Optional[float], kind: str = "number") -> str:
    """Format a single metric value for the prompt text block."""
    if value is None:
        return "N/A"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "score":
        return str(int(value))
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _build_prompt(summary: dict, years: list[int]) -> str:
    """
    Serialize the pre-computed summary dict into a structured plain-text block
    suitable for embedding in the LLM prompt.

    Pure read from the dict — no computation, no DB access.
    """
    company = summary.get("company", "Unknown")
    income  = summary.get("income_statement", {})
    balance = summary.get("balance_sheet", {})
    quality = summary.get("quality_metrics", {})
    risk    = summary.get("risk_analysis", {})

    lines = [
        f"Company: {company}",
        f"Years: {', '.join(str(y) for y in years)}",
        "",
    ]

    # ── Income Statement ──────────────────────────────────────────────────────
    lines.append("INCOME STATEMENT")
    for metric in ("revenue", "operating_income", "net_income"):
        entry  = income.get(metric, {})
        vals   = entry.get("values", {})
        yoy    = entry.get("yoy_pct")
        label  = metric.replace("_", " ").title()
        parts  = [f"{yr}: {_fmt(vals.get(yr))}" for yr in years]
        yoy_str = f", YoY: {yoy:+.1f}%" if yoy is not None else ""
        lines.append(f"  {label}: {'; '.join(parts)}{yoy_str}")

    lines.append("")

    # ── Balance Sheet ─────────────────────────────────────────────────────────
    lines.append("BALANCE SHEET")
    for metric in ("total_assets", "total_liabilities", "total_equity"):
        entry = balance.get(metric, {})
        vals  = entry.get("values", {})
        label = metric.replace("_", " ").title()
        parts = [f"{yr}: {_fmt(vals.get(yr))}" for yr in years]
        lines.append(f"  {label}: {'; '.join(parts)}")

    lines.append("")

    # ── Financial Quality ─────────────────────────────────────────────────────
    lines.append("FINANCIAL QUALITY")
    for metric in ("gross_margin", "operating_margin", "net_margin"):
        entry = quality.get(metric, {})
        vals  = entry.get("values", {})
        label = metric.replace("_", " ").title()
        parts = [f"{yr}: {_fmt(vals.get(yr), 'pct')}" for yr in years]
        lines.append(f"  {label}: {'; '.join(parts)}")

    cr_vals = quality.get("current_ratio", {}).get("values", {})
    lines.append(
        f"  Current Ratio: {'; '.join(f'{yr}: {_fmt(cr_vals.get(yr))}' for yr in years)}"
    )

    pio_vals = quality.get("piotroski_score", {}).get("values", {})
    pio_parts = [f"{yr}: {_fmt(pio_vals.get(yr), 'score')}" for yr in years]
    lines.append(f"  Piotroski F-Score (0-9): {'; '.join(pio_parts)}")

    flags = quality.get("risk_flags", [])
    lines.append(f"  Risk Flags: {', '.join(sorted(flags)) if flags else 'None'}")

    # ── Risk Assessment (populated by generate_deterministic_narrative) ────────
    if risk:
        lines.append("")
        lines.append("RISK ASSESSMENT")
        level = risk.get("overall_level", "N/A")
        score = risk.get("overall_score", 0)
        lines.append(f"  Overall Risk Level: {level} (composite score: {score:+d})")
        for cat in risk.get("categories", []):
            lines.append(
                f"  {cat['name']}: {cat['severity']} ({cat['score']:+d})"
            )

    return "\n".join(lines)


# =============================================================================
# Public API
# =============================================================================

def generate_llm_summary(summary: dict, years: list[int]) -> str:
    """
    Generate a 4-6 sentence executive summary using the Anthropic API.

    Inputs mirror build_financial_summary() output — all metrics are pre-computed;
    the LLM only writes prose, it does not compute anything.

    Parameters
    ----------
    summary : dict
        Output of build_financial_summary().
    years : list[int]
        Sorted list of fiscal years (same as summary["years"]).

    Returns
    -------
    str
        A 4-6 sentence plain-text executive summary.

    Raises
    ------
    KeyError
        If ANTHROPIC_API_KEY is not set in the environment.
    anthropic.APIError (or any subclass)
        On any API-level failure. The caller should catch Exception and fall
        back to the deterministic narrative.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    metrics_text = _build_prompt(summary, years)

    user_message = (
        "Based on the following pre-computed financial metrics, write a concise "
        "executive summary of the company's financial condition. "
        "Do not invent or estimate any numbers beyond what is explicitly provided.\n\n"
        f"{metrics_text}"
    )

    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    return " ".join(text_blocks).strip()
