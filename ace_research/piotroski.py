"""
Piotroski F-Score computation.

Deterministic implementation of all 9 Piotroski signals.
Every function reuses existing helpers from ace_research.db:
  - get_canonical_financial_fact()   (base metric at year t)
  - get_metric_previous_year()       (base metric at year t-1)
  - get_metric_ratio()               (ratio of two metrics)
  - get_metric_delta()               (year-over-year change)
  - insert_derived_metric()          (persistence with provenance)

No LLMs, no triggers, no inference. Missing data -> explicit None.
"""

import json

from ace_research.db import (
    get_canonical_financial_fact,
    get_metric_previous_year,
    get_metric_ratio,
    get_metric_delta,
    insert_derived_metric,
)


# ============================================================
# Profitability Signals (4 points)
# ============================================================

def compute_roa_signal(company: str, year: int) -> dict:
    """
    Signal 1: ROA > 0

    ROA = net_income / total_assets
    Score 1 if positive, 0 if zero or negative, None if missing.
    """
    net_income = get_canonical_financial_fact("net_income", year, company)
    total_assets = get_canonical_financial_fact("total_assets", year, company)

    roa = get_metric_ratio("net_income", "total_assets", year, company)

    signal = None
    if roa is not None:
        signal = roa > 0

    return {
        "signal": "roa_positive",
        "score": _bool_to_score(signal),
        "value": roa,
        "inputs": {
            "net_income": net_income,
            "total_assets": total_assets,
        },
    }


def compute_cfo_signal(company: str, year: int) -> dict:
    """
    Signal 2: Operating cash flow > 0

    Score 1 if positive, 0 if zero or negative, None if missing.
    """
    cfo = get_canonical_financial_fact("operating_cash_flow", year, company)

    signal = None
    if cfo is not None:
        signal = cfo > 0

    return {
        "signal": "cfo_positive",
        "score": _bool_to_score(signal),
        "value": cfo,
        "inputs": {
            "operating_cash_flow": cfo,
        },
    }


def compute_delta_roa_signal(company: str, year: int) -> dict:
    """
    Signal 3: Change in ROA > 0 (year t vs year t-1)

    ROA_t = net_income_t / total_assets_t
    ROA_t1 = net_income_(t-1) / total_assets_(t-1)
    Score 1 if ROA_t > ROA_t1, else 0. None if either year missing.
    """
    roa_current = get_metric_ratio("net_income", "total_assets", year, company)
    roa_prior = get_metric_ratio("net_income", "total_assets", year - 1, company)

    delta_roa = None
    if roa_current is not None and roa_prior is not None:
        delta_roa = roa_current - roa_prior

    signal = None
    if delta_roa is not None:
        signal = delta_roa > 0

    return {
        "signal": "delta_roa_positive",
        "score": _bool_to_score(signal),
        "value": delta_roa,
        "inputs": {
            "roa_current": roa_current,
            "roa_prior": roa_prior,
            "year_current": year,
            "year_prior": year - 1,
        },
    }


def compute_accruals_signal(company: str, year: int) -> dict:
    """
    Signal 4: Accruals < 0

    Accruals = (operating_cash_flow - net_income) / total_assets
    Score 1 if accruals ratio is positive (CFO > net_income), else 0.

    Note: The Piotroski convention is that quality earnings means
    CFO exceeds net income. We compute accruals as CFO/assets - ROA.
    A positive value means cash flow exceeds accounting income.
    """
    cfo = get_canonical_financial_fact("operating_cash_flow", year, company)
    net_income = get_canonical_financial_fact("net_income", year, company)
    total_assets = get_canonical_financial_fact("total_assets", year, company)

    accrual_ratio = None
    if cfo is not None and net_income is not None and total_assets is not None:
        if total_assets != 0:
            # Piotroski: score 1 when CFO/Assets > ROA (i.e., CFO > NI)
            accrual_ratio = (cfo - net_income) / total_assets

    signal = None
    if accrual_ratio is not None:
        signal = accrual_ratio > 0  # CFO exceeds net income -> good quality

    return {
        "signal": "accruals_quality",
        "score": _bool_to_score(signal),
        "value": accrual_ratio,
        "inputs": {
            "operating_cash_flow": cfo,
            "net_income": net_income,
            "total_assets": total_assets,
        },
    }


# ============================================================
# Leverage, Liquidity, Source of Funds (3 points)
# ============================================================

def compute_delta_leverage_signal(company: str, year: int) -> dict:
    """
    Signal 5: Change in leverage < 0

    Leverage = long_term_debt / total_assets
    Score 1 if leverage decreased year-over-year, else 0.
    None if either year missing.
    """
    leverage_current = get_metric_ratio(
        "long_term_debt", "total_assets", year, company
    )
    leverage_prior = get_metric_ratio(
        "long_term_debt", "total_assets", year - 1, company
    )

    delta_leverage = None
    if leverage_current is not None and leverage_prior is not None:
        delta_leverage = leverage_current - leverage_prior

    signal = None
    if delta_leverage is not None:
        signal = delta_leverage < 0

    return {
        "signal": "delta_leverage_negative",
        "score": _bool_to_score(signal),
        "value": delta_leverage,
        "inputs": {
            "leverage_current": leverage_current,
            "leverage_prior": leverage_prior,
            "year_current": year,
            "year_prior": year - 1,
        },
    }


def compute_delta_liquidity_signal(company: str, year: int) -> dict:
    """
    Signal 6: Change in liquidity > 0

    Liquidity = current_assets / current_liabilities (current ratio)
    Score 1 if current ratio increased year-over-year, else 0.
    None if either year missing.
    """
    liquidity_current = get_metric_ratio(
        "current_assets", "current_liabilities", year, company
    )
    liquidity_prior = get_metric_ratio(
        "current_assets", "current_liabilities", year - 1, company
    )

    delta_liquidity = None
    if liquidity_current is not None and liquidity_prior is not None:
        delta_liquidity = liquidity_current - liquidity_prior

    signal = None
    if delta_liquidity is not None:
        signal = delta_liquidity > 0

    return {
        "signal": "delta_liquidity_positive",
        "score": _bool_to_score(signal),
        "value": delta_liquidity,
        "inputs": {
            "liquidity_current": liquidity_current,
            "liquidity_prior": liquidity_prior,
            "year_current": year,
            "year_prior": year - 1,
        },
    }


def compute_no_equity_issuance_signal(company: str, year: int) -> dict:
    """
    Signal 7: No equity issuance (shares outstanding did not increase)

    Score 1 if shares_outstanding_t <= shares_outstanding_(t-1), else 0.
    None if either year missing.
    """
    shares_current = get_canonical_financial_fact(
        "shares_outstanding", year, company
    )
    shares_prior = get_metric_previous_year(
        "shares_outstanding", year, company
    )

    delta_shares = None
    if shares_current is not None and shares_prior is not None:
        delta_shares = shares_current - shares_prior

    signal = None
    if delta_shares is not None:
        signal = delta_shares <= 0

    return {
        "signal": "no_equity_issuance",
        "score": _bool_to_score(signal),
        "value": delta_shares,
        "inputs": {
            "shares_current": shares_current,
            "shares_prior": shares_prior,
            "year_current": year,
            "year_prior": year - 1,
        },
    }


# ============================================================
# Operating Efficiency (2 points)
# ============================================================

def compute_delta_gross_margin_signal(company: str, year: int) -> dict:
    """
    Signal 8: Change in gross margin > 0

    Gross margin = gross_profit / revenue
    Score 1 if gross margin increased year-over-year, else 0.
    None if either year missing.

    Falls back to computing gross_profit as (revenue - cost_of_revenue)
    if gross_profit is not directly available.
    """
    gm_current = _get_gross_margin(company, year)
    gm_prior = _get_gross_margin(company, year - 1)

    delta_gm = None
    if gm_current is not None and gm_prior is not None:
        delta_gm = gm_current - gm_prior

    signal = None
    if delta_gm is not None:
        signal = delta_gm > 0

    return {
        "signal": "delta_gross_margin_positive",
        "score": _bool_to_score(signal),
        "value": delta_gm,
        "inputs": {
            "gross_margin_current": gm_current,
            "gross_margin_prior": gm_prior,
            "year_current": year,
            "year_prior": year - 1,
        },
    }


def compute_delta_asset_turnover_signal(company: str, year: int) -> dict:
    """
    Signal 9: Change in asset turnover > 0

    Asset turnover = revenue / total_assets
    Score 1 if asset turnover increased year-over-year, else 0.
    None if either year missing.
    """
    at_current = get_metric_ratio("revenue", "total_assets", year, company)
    at_prior = get_metric_ratio("revenue", "total_assets", year - 1, company)

    delta_at = None
    if at_current is not None and at_prior is not None:
        delta_at = at_current - at_prior

    signal = None
    if delta_at is not None:
        signal = delta_at > 0

    return {
        "signal": "delta_asset_turnover_positive",
        "score": _bool_to_score(signal),
        "value": delta_at,
        "inputs": {
            "asset_turnover_current": at_current,
            "asset_turnover_prior": at_prior,
            "year_current": year,
            "year_prior": year - 1,
        },
    }


# ============================================================
# Aggregator
# ============================================================

# Ordered list of all signal functions
SIGNAL_FUNCTIONS = [
    compute_roa_signal,
    compute_cfo_signal,
    compute_delta_roa_signal,
    compute_accruals_signal,
    compute_delta_leverage_signal,
    compute_delta_liquidity_signal,
    compute_no_equity_issuance_signal,
    compute_delta_gross_margin_signal,
    compute_delta_asset_turnover_signal,
]


def compute_piotroski_score(company: str, year: int) -> dict:
    """
    Compute the full Piotroski F-Score (0-9) for a company and year.

    Returns a dict with:
        - total_score: int (0-9) or None if insufficient data
        - max_possible: int (number of signals that could be computed)
        - signals: dict mapping signal name -> signal result dict
        - company: str
        - year: int

    Each signal in signals contains:
        - score: 1, 0, or None
        - value: the numeric value used for the decision
        - inputs: dict of raw canonical values used
    """
    signals = {}
    total = 0
    computable = 0

    for fn in SIGNAL_FUNCTIONS:
        result = fn(company, year)
        name = result["signal"]
        signals[name] = result

        if result["score"] is not None:
            total += result["score"]
            computable += 1

    return {
        "company": company,
        "year": year,
        "total_score": total if computable > 0 else None,
        "max_possible": computable,
        "signals": signals,
    }


# ============================================================
# Persistence
# ============================================================

def persist_piotroski_score(company: str, year: int) -> dict:
    """
    Compute and persist Piotroski F-Score to derived_metrics table.

    Stores:
        - Individual signal scores as separate derived_metrics rows
        - Total score as a summary row
        - Full provenance (inputs) for each signal

    Returns the computed score dict.
    """
    result = compute_piotroski_score(company, year)

    # Store each signal individually
    for name, signal_data in result["signals"].items():
        provenance = json.dumps({
            "signal": name,
            "inputs": _serialize_inputs(signal_data["inputs"]),
            "raw_value": signal_data["value"],
        })

        insert_derived_metric(
            company=company,
            year=year,
            metric=f"piotroski_{name}",
            value=signal_data["score"],
            metric_type="single_year",
            input_components=provenance,
        )

    # Store total score
    total_provenance = json.dumps({
        "total_score": result["total_score"],
        "max_possible": result["max_possible"],
        "signal_scores": {
            name: sig["score"]
            for name, sig in result["signals"].items()
        },
    })

    insert_derived_metric(
        company=company,
        year=year,
        metric="piotroski_f_score",
        value=result["total_score"],
        metric_type="single_year",
        input_components=total_provenance,
    )

    return result


# ============================================================
# Internal helpers
# ============================================================

def _bool_to_score(value):
    """Convert True/False/None -> 1/0/None."""
    if value is None:
        return None
    return 1 if value else 0


def _get_gross_margin(company: str, year: int):
    """
    Compute gross margin for a company/year.

    Tries gross_profit / revenue first.
    Falls back to (revenue - cost_of_revenue) / revenue.
    Returns None if neither is possible.
    """
    revenue = get_canonical_financial_fact("revenue", year, company)
    if revenue is None or revenue == 0:
        return None

    gross_profit = get_canonical_financial_fact("gross_profit", year, company)
    if gross_profit is not None:
        return gross_profit / revenue

    cost_of_revenue = get_canonical_financial_fact("cost_of_revenue", year, company)
    if cost_of_revenue is not None:
        return (revenue - cost_of_revenue) / revenue

    return None


def _serialize_inputs(inputs: dict) -> dict:
    """Ensure all input values are JSON-serializable."""
    serialized = {}
    for k, v in inputs.items():
        if isinstance(v, float):
            serialized[k] = round(v, 8)
        else:
            serialized[k] = v
    return serialized


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compute Piotroski F-Score")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--year", required=True, type=int, help="Fiscal year")
    parser.add_argument(
        "--persist", action="store_true",
        help="Store results in derived_metrics table"
    )
    args = parser.parse_args()

    if args.persist:
        result = persist_piotroski_score(args.company, args.year)
    else:
        result = compute_piotroski_score(args.company, args.year)

    print(f"\n{'='*60}")
    print(f"Piotroski F-Score: {result['company']} ({result['year']})")
    print(f"{'='*60}")
    print(f"Total Score: {result['total_score']} / {result['max_possible']} computable (out of 9)")
    print(f"{'='*60}")

    categories = {
        "Profitability": [
            "roa_positive", "cfo_positive",
            "delta_roa_positive", "accruals_quality",
        ],
        "Leverage/Liquidity": [
            "delta_leverage_negative", "delta_liquidity_positive",
            "no_equity_issuance",
        ],
        "Efficiency": [
            "delta_gross_margin_positive", "delta_asset_turnover_positive",
        ],
    }

    for category, signal_names in categories.items():
        print(f"\n  {category}:")
        for name in signal_names:
            sig = result["signals"].get(name, {})
            score = sig.get("score")
            value = sig.get("value")
            score_str = str(score) if score is not None else "N/A"
            value_str = f"{value:.6f}" if isinstance(value, float) else str(value)
            print(f"    {name:35s} -> {score_str:3s}  (value: {value_str})")

    if args.persist:
        print(f"\nResults persisted to derived_metrics table.")
