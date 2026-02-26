"""
backtest.py

Deterministic backtesting engine: evaluates whether higher Piotroski scores
correlate with stronger forward financial performance.

Three-layer architecture
------------------------
Layer 1 — Signal Layer (existing):
    get_piotroski_from_db(company, year)  [from experiments.py]

Layer 2 — Forward Performance Provider (this file):
    compute_forward_performance(company, year, mode="financial")
    Isolated dispatcher so future mode="market" requires no changes here.

Layer 3 — Aggregation Engine (this file):
    aggregate_by_score_bucket(records)
    Pure function — knows nothing about how performance was computed.

Main entrypoint
---------------
    run_piotroski_backtest(companies, mode="financial") -> dict

CLI
---
    python -m ace_research.backtest
"""

from __future__ import annotations

from typing import Optional

from ace_research.db import (
    get_available_years,
    get_canonical_financial_fact,
    get_metric_ratio,
)
from ace_research.experiments import get_piotroski_from_db


# =============================================================================
# Layer 2 — Forward Performance Provider
# =============================================================================

def _compute_financial_performance(company: str, year: int) -> Optional[dict]:
    """
    Compute forward financial performance from year T to T+1 using existing helpers.

    Metrics:
        revenue_growth     = (revenue[T+1] - revenue[T]) / revenue[T]
        net_income_growth  = (net_income[T+1] - net_income[T]) / net_income[T]
        roa_change         = roa[T+1] - roa[T],  where roa = net_income / total_assets

    Returns None if no forward metric can be computed (T+1 data entirely absent).
    Individual metric values within the returned dict may be None when their
    specific inputs are unavailable or denominator is zero.
    """
    t1 = year + 1

    # Revenue growth
    rev_t = get_canonical_financial_fact("revenue", year, company)
    rev_t1 = get_canonical_financial_fact("revenue", t1, company)
    if rev_t is not None and rev_t != 0 and rev_t1 is not None:
        revenue_growth = (rev_t1 - rev_t) / rev_t
    else:
        revenue_growth = None

    # Net income growth
    ni_t = get_canonical_financial_fact("net_income", year, company)
    ni_t1 = get_canonical_financial_fact("net_income", t1, company)
    if ni_t is not None and ni_t != 0 and ni_t1 is not None:
        net_income_growth = (ni_t1 - ni_t) / ni_t
    else:
        net_income_growth = None

    # ROA change: roa[T+1] - roa[T]
    roa_t = get_metric_ratio("net_income", "total_assets", year, company)
    roa_t1 = get_metric_ratio("net_income", "total_assets", t1, company)
    if roa_t is not None and roa_t1 is not None:
        roa_change = roa_t1 - roa_t
    else:
        roa_change = None

    # If no forward metric is computable, treat T+1 as absent
    if revenue_growth is None and net_income_growth is None and roa_change is None:
        return None

    return {
        "revenue_growth": revenue_growth,
        "net_income_growth": net_income_growth,
        "roa_change": roa_change,
    }


def compute_forward_performance(
    company: str, year: int, mode: str = "financial"
) -> Optional[dict]:
    """
    Dispatcher for forward performance calculation.

    mode="financial"  -> revenue_growth, net_income_growth, roa_change (T to T+1)
    mode="market"     -> NotImplementedError (reserved for future price-return mode)

    The aggregation engine (Layer 3) is fully independent of which mode is used.
    Adding a new mode only requires implementing _compute_<mode>_performance()
    and adding an elif branch here.
    """
    if mode == "financial":
        return _compute_financial_performance(company, year)
    raise NotImplementedError(
        f"Performance mode '{mode}' is not implemented. "
        "Add a _compute_{mode}_performance() function and wire it here."
    )


# =============================================================================
# Layer 3 — Aggregation Engine
# =============================================================================

def _score_bucket(score: int) -> str:
    """Map a Piotroski score to its bucket label."""
    if score >= 7:
        return "high"
    elif score >= 4:
        return "medium"
    return "low"


def _avg(values: list) -> Optional[float]:
    """Mean of a list, excluding None entries. Returns None when no valid data."""
    valid = [v for v in values if v is not None]
    return round(sum(valid) / len(valid), 4) if valid else None


def _overall_confidence(total: int) -> float:
    """Confidence solely based on total observation count."""
    if total >= 15:
        return 0.9
    elif total >= 8:
        return 0.7
    elif total >= 3:
        return 0.5
    return 0.3


def aggregate_by_score_bucket(records: list[dict]) -> dict:
    """
    Bucket records by Piotroski score range and compute average forward metrics.

    Input record shape:
        {
            "score": int,
            "performance": {
                "revenue_growth": float | None,
                "net_income_growth": float | None,
                "roa_change": float | None,
            }
        }

    Score buckets:
        High   — 7 to 9
        Medium — 4 to 6
        Low    — 0 to 3

    Returns:
        {
            "high":   {"avg_revenue_growth": ..., "avg_net_income_growth": ...,
                       "avg_roa_change": ..., "sample_size": int},
            "medium": { ... },
            "low":    { ... },
            "total_observations": int,
            "confidence": float,
            "confidence_label": "low" | "medium" | "high",
        }
    """
    buckets: dict[str, dict[str, list]] = {
        "high":   {"revenue_growth": [], "net_income_growth": [], "roa_change": []},
        "medium": {"revenue_growth": [], "net_income_growth": [], "roa_change": []},
        "low":    {"revenue_growth": [], "net_income_growth": [], "roa_change": []},
    }

    for record in records:
        bucket = _score_bucket(record["score"])
        perf = record["performance"]
        for metric in ("revenue_growth", "net_income_growth", "roa_change"):
            buckets[bucket][metric].append(perf.get(metric))

    result = {}
    for bucket_name, metrics in buckets.items():
        result[bucket_name] = {
            "avg_revenue_growth":    _avg(metrics["revenue_growth"]),
            "avg_net_income_growth": _avg(metrics["net_income_growth"]),
            "avg_roa_change":        _avg(metrics["roa_change"]),
            "sample_size":           len(metrics["revenue_growth"]),
        }

    total = len(records)
    confidence = _overall_confidence(total)
    confidence_label = (
        "high" if confidence >= 0.8 else "medium" if confidence >= 0.5 else "low"
    )

    result["total_observations"] = total
    result["confidence"] = confidence
    result["confidence_label"] = confidence_label

    return result


# =============================================================================
# Main Entrypoint
# =============================================================================

def run_piotroski_backtest(
    companies: list[str], mode: str = "financial"
) -> dict:
    """
    Run a Piotroski backtest across all available years for the given companies.

    For each (company, year T) where T+1 also exists in the DB:
        1. Retrieve Piotroski score at T via get_piotroski_from_db() (Layer 1).
        2. Compute forward performance from T to T+1 via compute_forward_performance()
           (Layer 2).
        3. Collect record; skip if score or performance is unavailable.

    Aggregates via aggregate_by_score_bucket() (Layer 3) and returns:
        {
            "high":   {...},
            "medium": {...},
            "low":    {...},
            "total_observations": int,
            "confidence": float,
            "confidence_label": str,
        }
    """
    records = []

    for company in companies:
        years = sorted(get_available_years(company=company))
        year_set = set(years)

        for year in years:
            if year + 1 not in year_set:
                continue  # No forward year available — skip

            piotroski_result = get_piotroski_from_db(company, year)
            score = piotroski_result.get("total_score")
            if score is None:
                continue  # Cannot bucket without a score

            performance = compute_forward_performance(company, year, mode=mode)
            if performance is None:
                continue  # No computable forward metrics — skip

            records.append({
                "company": company,
                "year": year,
                "score": score,
                "performance": performance,
            })

    return aggregate_by_score_bucket(records)


# =============================================================================
# CLI
# =============================================================================

def _fmt_pct(value: Optional[float]) -> str:
    return f"{value * 100:+.2f}%" if value is not None else "N/A"


def _fmt_dec(value: Optional[float]) -> str:
    return f"{value:+.4f}" if value is not None else "N/A"


def _print_bucket(label: str, data: dict) -> None:
    print(f"{label}:")
    print(f"    Avg Revenue Growth:    {_fmt_pct(data['avg_revenue_growth'])}")
    print(f"    Avg Net Income Growth: {_fmt_pct(data['avg_net_income_growth'])}")
    print(f"    Avg ROA Change:        {_fmt_dec(data['avg_roa_change'])}")
    print(f"    Observations:          {data['sample_size']}")
    print()


if __name__ == "__main__":
    from ace_research.db import get_available_companies

    companies = get_available_companies()
    if not companies:
        print("No companies found in database.")
    else:
        result = run_piotroski_backtest(companies)
        print()
        print("=== Piotroski Backtest Results ===")
        print(f"Total Observations: {result['total_observations']}")
        print(f"Confidence:         {result['confidence']} ({result['confidence_label']})")
        print()
        _print_bucket("High (7-9)",   result["high"])
        _print_bucket("Medium (4-6)", result["medium"])
        _print_bucket("Low (0-3)",    result["low"])
