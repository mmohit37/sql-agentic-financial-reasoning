"""
experiments.py
Reproduction scaffold for ACE (Agentic Context Engineering) on FINER benchmark.
Simulates the three-agent workflow: Generator → Reflector → Curator.
"""

import json
from typing import List, Dict
import sqlite3
import re
from collections import defaultdict
from ace_research.generator import format_comparison_answer
from ace_research.db import get_available_aggregations, get_available_metrics, get_confidence_history, get_available_years, get_available_companies
from ace_research.db import query_aggregate, get_canonical_financial_fact, get_derived_metrics_by_prefix, get_metric_ratio
from ace_research.piotroski import compute_piotroski_score, persist_piotroski_score

derived_metrics = {
    "operating_margin": {
        "formula": "operating_income / revenue",
        "components": ["operating_income", "revenue"]
    },
    "gross_margin": {
        "formula": "gross_profit / revenue",
        "components": ["gross_profit", "revenue"]
    },
    "net_margin": {
        "formula": "net_income / revenue",
        "components": ["net_income", "revenue"]
    },
    "return_on_assets": {
        "formula": "net_income / total_assets",
        "components": ["net_income", "total_assets"]
    },
    "return_on_equity": {
        "formula": "net_income / total_equity",
        "components": ["net_income", "total_equity"]
    },
    "debt_to_equity": {
        "formula": "total_liabilities / total_equity",
        "components": ["total_liabilities", "total_equity"]
    },
    "current_ratio": {
        "formula": "current_assets / current_liabilities",
        "components": ["current_assets", "current_liabilities"]
    },
    "ebitda_margin": {
        "formula": "ebitda / revenue",
        "components": ["ebitda", "revenue"]
    },
    "asset_turnover": {
        "formula": "revenue / total_assets",
        "components": ["revenue", "total_assets"]
    },
    "debt_ratio": {
        "formula": "total_liabilities / total_assets",
        "components": ["total_liabilities", "total_assets"]
    },
    "equity_ratio": {
        "formula": "total_equity / total_assets",
        "components": ["total_equity", "total_assets"]
    },
    "equity_multiplier": {
        "formula": "total_assets / total_equity",
        "components": ["total_assets", "total_equity"]
    },
    "return_on_invested_capital": {
        "formula": "net_income / (total_equity + total_liabilities)",
        "components": ["net_income", "total_equity", "total_liabilities"]
    }
}

PIOTROSKI_KEYWORDS = ["piotroski", "f-score", "f score", "fscore", "financial strength score", "financial strength"]
PIOTROSKI_TREND_KEYWORDS = ["trend", "over time", "across years", "changed", "improved", "history", "trajectory"]
RISK_KEYWORDS = ["risk", "warning", "red flag", "danger", "concern", "alert", "weakness", "deteriorat"]

trend_keywords = {
    "trend": ["trend", "over time", "across years"],
    "increase": ["increase", "increasing", "growth", "grew", "rising"],
    "decrease": ["decrease", "declining", "drop", "fell", "falling"],
    "compare": ["compare", "comparison", "vs", "versus"]
}

# ----------------------------
# Agentic Roles
# ----------------------------

class Generator:
    """Produces reasoning and answers using a playbook."""
    def __init__(self, playbook: List[str]):
        self.playbook = playbook
    
    def build_reasoning_plan(self, question: str) -> Dict:
        q = question.lower()

        companies = infer_companies(q, get_available_companies())
        if not companies:
            companies = ["ACME Corp"]

        years = re.findall(r"(20\d{2})", q)
        year = int(years[0]) if years else None

        comparison_keywords = ["vs", "versus", "compare", "comparison", "and"]
        is_comparison = any(k in q for k in comparison_keywords) and len(companies) > 1
        is_trend = any(word in q for word in trend_keywords["trend"])

        metric = None
        for m in get_available_metrics():
            if m.replace("_", " ") in q:
                metric = m
                break

        is_derived = metric in derived_metrics if metric else False
        is_piotroski = any(kw in q for kw in PIOTROSKI_KEYWORDS)
        is_piotroski_trend = is_piotroski and (
            any(kw in q for kw in PIOTROSKI_TREND_KEYWORDS)
            or bool(re.search(r"last\s+\d+\s+years?", q))
            or bool(re.search(r"from\s+20\d{2}\s+to\s+20\d{2}", q))
            or bool(re.search(r"since\s+20\d{2}", q))
        )
        is_risk_flags = (
            not is_piotroski
            and any(kw in q for kw in RISK_KEYWORDS)
        )

        if is_piotroski_trend:
            intent = "piotroski_trend"
        elif is_piotroski:
            intent = "piotroski"
        elif is_risk_flags:
            intent = "risk_flags"
        elif is_trend:
            intent = "trend"
        elif is_comparison:
            intent = "comparison"
        elif is_derived:
            intent = "derived_metric"
        else:
            intent = "base_metric"

        base_metrics = (
            derived_metrics[metric]["components"]
            if is_derived and metric in derived_metrics
            else []
        )

        return {
            "intent": intent,
            "metric": metric if not is_piotroski else "piotroski_f_score",
            "base_metrics": base_metrics,
            "companies": companies,
            "year": year,
            "is_trend": is_trend,
            "is_comparison": is_comparison,
            "is_derived": is_derived,
            "is_piotroski": is_piotroski,
            "is_piotroski_trend": is_piotroski_trend,
            "is_risk_flags": is_risk_flags
        }

    def generate(self, question: str) -> Dict:
        reasoning = f"Interpreting the question: {question}"
        
        q = question.lower()

        plan = self.build_reasoning_plan(question)
        reasoning += f" → plan={plan['intent']}"

        available_companies = get_available_companies()
        companies = infer_companies(q, available_companies)

        # Fallback
        if not companies:
            companies = ["ACME Corp"]

        years = re.findall(r"(20\d{2})", q)
        year = int(years[0]) if years else 2023
        reasoning += f" → inferred year={year}"
        
        comparison_keywords = ["vs", "versus", "compare", "comparison", "and"]
        is_comparison = any(k in q for k in comparison_keywords) and len(companies) > 1

        # Piotroski trend: intercept before single-company / comparison routing
        if plan.get("is_piotroski_trend"):
            year_range = extract_piotroski_year_range(question)
            company = companies[0] if companies else None
            return self.handle_piotroski_trend(company, year_range, reasoning)

        # Piotroski intent: intercept before derived/base metric routing
        if plan.get("is_piotroski"):
            return self.handle_piotroski(companies, year, reasoning)

        # Risk flag assessment
        if plan.get("is_risk_flags"):
            company = companies[0] if companies else None
            return self.handle_risk_flags(company, year, reasoning)

        agg = None

        # Identify complex metric
        for derived, spec in derived_metrics.items():
            if derived.replace("_", " ") in q:
                reasoning += f" → identified derived metric: {derived}"
                return self.compute_derived_metric(
                    derived, 
                    spec, 
                    q, 
                    reasoning,
                    companies,
                    year,
                    is_comparison)

        available_metrics = get_available_metrics()

        metric = None
        for m in available_metrics:
            if m.replace("_", " ") in q:
                metric = m
                reasoning += f" → matched metric from schema: {metric}"
                break
        
        unsupported_aggs = ["median"]

        for word in unsupported_aggs:
            if word in q:
                return {
                    "reasoning": reasoning + f" → aggregation '{word}' not supported by schema",
                    "used_bullets": [],
                    "final_answer": None,
                    "used_aggregation": False,
                    "is_derived": False,
                    "missing_components": True
                }        

        if metric is None:
            return {
                "reasoning": reasoning + " → no metric found in DB schema",
                "used_bullets": [],
                "final_answer": None,
                "used_aggregation": False,
                "is_derived": False,
                "missing_components": True
            }

        intent_to_agg = {
            "total": "SUM",
            "average": "AVG",
            "sum": "SUM",
            "avg": "AVG",
            "mean": "AVG",
            "max": "MAX",
            "min": "MIN",
            "count": "COUNT",
        }

        if any(word in q for word in trend_keywords["trend"]):
            trend_results = {}

            for company in companies:
                years = get_available_years(company=company)
                trend_result = analyze_trend(metric, years, company=company)
                trend_results[company] = trend_result

            if is_comparison and not agg:
                comparison = compare_canonical_fact(metric, year, companies)

                return {
                    "reasoning": reasoning + f" → compared {metric} across {companies}",
                    "final_answer": comparison,
                    "used_aggregation": False,
                    "is_derived": False,
                    "is_comparison": True,
                    "missing_components": comparison["winner"] is None
                }

            if is_comparison:
                return {
                    "reasoning": reasoning + f" → analyzed trend per company",
                    "final_answer": {
                        company: trend_results[company]["trend"]
                        for company in trend_results
                        },
                    "trend_values": {
                        company: trend_results[company]["values"]
                        for company in trend_results
                        },
                    "used_aggregation": False,
                    "is_derived": False,
                    "is_trend": True,
                    "is_comparison": True,
                    "companies": companies,
                    "missing_components": any(
                not trend_results[c]["values"] for c in trend_results
                 )
                }

            # single-company fallback
            company = companies[0]
            return {
                "reasoning": reasoning + f" → analyzed trend for {company}",
                "final_answer": trend_results[company]["trend"],
                "trend_values": trend_results[company]["values"],
                "used_aggregation": False,
                "is_derived": False,
                "is_trend": True,
                "is_comparison": False,
                "companies": companies,
                "missing_components": not trend_results[company]["values"]
            }


        requested_agg = None
        for word, agg in intent_to_agg.items():
            if word in q:
                requested_agg = agg
                break
        
        available_aggs = get_available_aggregations()

        if requested_agg in available_aggs:
            agg = requested_agg
        else:
            agg = None
        
        results = {}
        
        if requested_agg and requested_agg not in available_aggs:
            return {
                "reasoning": reasoning + f" → aggregation '{requested_agg}' not supported by schema",
                "used_bullets": [],
                "final_answer": None,
                "used_aggregation": False,
                "is_derived": False,
                "missing_components": True
            }
        
        for company in companies:
            if agg:
                value = query_aggregate(metric, agg, year, company)
                reasoning += f" → querying SQL for ({agg}({metric}), {year}, {company})"
            else:
                value = get_canonical_financial_fact(metric, year, company)
                reasoning += f" → querying SQL for ({metric}, {year}, {company})"
            
            results[company] = value
        
        if is_comparison:
            final_answer = format_comparison_answer(
                metric = metric,
                year = year,
                results = results,
            )

        else:
            final_answer = results[companies[0]]

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": final_answer,
            "used_aggregation": agg is not None,
            "is_derived": False,
            "missing_components": (
                    any(v is None for v in results.values())
                    if is_comparison
                    else final_answer is None
            ),
            "is_comparison": is_comparison,
            "companies": companies
        }
    
    def compute_derived_metric(self, name, spec, q, reasoning, companies, year, is_comparison):

        def get_component_value(component: str, year: int, company: str):
            return get_canonical_financial_fact(component, year, company)

        formula = spec["formula"]

        # Extract components
        components = [
            token for token in formula.replace("(", "").replace(")", "").split()
            if token.isidentifier()
        ]

        results = {}
        missing = {}

        for company in companies:
            values = {}

            for component in components:
                val = get_component_value(component, year, company)
                if val is None:
                    reasoning += f" → missing canonical component {component} for {company}"
                    return {
                        "reasoning": reasoning,
                        "final_answer": None,
                        "used_aggregation": False,
                        "is_derived": True,
                        "missing_components": True
                    }
                values[component] = val
                reasoning += f" → fetched {component}={val} for {company}"

            if values is None:
                results[company] = None
                missing[company] = True
                continue

            try:
                safe_locals = {
                    **values,
                    "abs": abs,
                    "min": min,
                    "max": max,
                    "round": round
                }
                result = eval(formula, {"__builtins__": {}}, safe_locals)
                results[company] = round(result, 4)
                missing[company] = False
                reasoning += f" → computed {name}={result} for {company}"
            except ZeroDivisionError:
                results[company] = None
                missing[company] = True
                reasoning += f" → division by zero for {company}"

        # Decide return shape
        if is_comparison:
            final_answer = results
            missing_components = any(missing.values())
        else:
            company = companies[0]
            final_answer = (
                round(results[company], 4)
                if results[company] is not None
                else None
            )
            missing_components = missing[company]

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": final_answer,
            "used_aggregation": False,
            "is_derived": True,
            "missing_components": missing_components,
            "is_comparison": is_comparison,
            "companies": companies
        }

    def handle_piotroski(self, companies: list, year: int, reasoning: str) -> Dict:
        """
        Handle Piotroski F-Score queries.

        Routes to comparison handler when multiple companies detected.
        Uses Option C caching: check DB first, compute only if missing.
        Returns structured response with score, signals, explanation, confidence.
        """
        if len(companies) > 1:
            return self.handle_piotroski_comparison(companies, year, reasoning)

        company = companies[0] if companies else None
        if not company:
            return {
                "reasoning": reasoning + " -> no company identified for Piotroski query",
                "final_answer": None,
                "used_aggregation": False,
                "is_derived": False,
                "is_piotroski": True,
                "missing_components": True,
                "companies": [],
            }

        result = get_piotroski_from_db(company, year)

        confidence = compute_piotroski_confidence(result["max_possible"])
        confidence_label = (
            "high" if confidence >= 0.8
            else "medium" if confidence >= 0.5
            else "low"
        )
        explanation = build_piotroski_explanation(result)

        piotroski_answer = {
            "company": company,
            "year": year,
            "piotroski_score": result["total_score"],
            "max_score": 9,
            "signals": {
                name: sig["score"] for name, sig in result["signals"].items()
            },
            "explanation": explanation,
            "confidence": confidence,
            "confidence_label": confidence_label,
        }

        reasoning += (
            f" -> retrieved Piotroski F-Score for {company} ({year}):"
            f" {result['total_score']}/{result['max_possible']}"
        )

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": piotroski_answer,
            "used_aggregation": False,
            "is_derived": False,
            "is_piotroski": True,
            "is_piotroski_trend": False,
            "missing_components": result["total_score"] is None,
            "is_comparison": False,
            "companies": companies,
            "intent": "piotroski",
            "metric": "piotroski_f_score",
            "year": year,
            "confidence": confidence,
        }

    def handle_piotroski_comparison(self, companies: list, year: int, reasoning: str) -> Dict:
        """
        Handle multi-company Piotroski F-Score comparison.

        For each company: retrieve (or compute+persist) via get_piotroski_from_db().
        Rank by total_score descending, with alphabetical tiebreak.
        Confidence = minimum of individual confidences.
        """
        entries = []

        for company in companies:
            result = get_piotroski_from_db(company, year)
            conf = compute_piotroski_confidence(result["max_possible"])
            entries.append({
                "company": company,
                "score": result["total_score"],
                "max_possible": result["max_possible"],
                "confidence": conf,
            })
            reasoning += (
                f" -> {company}: score={result['total_score']}/{result['max_possible']}"
            )

        # Sort: descending by score (None sorts last), then alphabetical tiebreak
        ranking = sorted(
            entries,
            key=lambda e: (
                e["score"] if e["score"] is not None else -1,
                -ord(e["company"][0]),  # reverse alpha for secondary sort
            ),
            reverse=True,
        )

        # Determine winner or tie
        scoreable = [e for e in ranking if e["score"] is not None]
        if len(scoreable) >= 2 and scoreable[0]["score"] == scoreable[1]["score"]:
            winner = None  # tie
        elif scoreable:
            winner = scoreable[0]["company"]
        else:
            winner = None

        # Confidence = minimum across all companies (penalizes weak data)
        all_confidences = [e["confidence"] for e in entries]
        comparison_confidence = min(all_confidences) if all_confidences else 0.2
        confidence_label = (
            "high" if comparison_confidence >= 0.8
            else "medium" if comparison_confidence >= 0.5
            else "low"
        )

        explanation = build_piotroski_comparison_explanation(ranking, year, winner)

        comparison_answer = {
            "year": year,
            "ranking": [
                {
                    "company": e["company"],
                    "score": e["score"],
                    "max_possible": e["max_possible"],
                    "confidence": e["confidence"],
                }
                for e in ranking
            ],
            "winner": winner,
            "explanation": explanation,
            "confidence": comparison_confidence,
            "confidence_label": confidence_label,
        }

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": comparison_answer,
            "used_aggregation": False,
            "is_derived": False,
            "is_piotroski": True,
            "is_piotroski_trend": False,
            "missing_components": not scoreable,
            "is_comparison": True,
            "companies": companies,
            "intent": "piotroski_comparison",
            "metric": "piotroski_f_score",
            "year": year,
            "confidence": comparison_confidence,
        }

    def handle_piotroski_trend(
        self, company: str, year_range: tuple, reasoning: str
    ) -> Dict:
        """
        Handle multi-year Piotroski F-Score trend analysis.

        For each year in range: retrieve (or compute+persist) via get_piotroski_from_db().
        Confidence = min of yearly confidences, penalized proportionally for missing years.
        """
        if not company:
            return {
                "reasoning": reasoning + " -> no company identified for Piotroski trend",
                "used_bullets": [],
                "final_answer": None,
                "used_aggregation": False,
                "is_derived": False,
                "is_piotroski": True,
                "is_piotroski_trend": True,
                "missing_components": True,
                "is_comparison": False,
                "companies": [],
                "intent": "piotroski_trend",
                "metric": "piotroski_f_score",
                "year": year_range[1],
                "confidence": 0.2,
            }

        start_year, end_year = year_range
        trend_data = []

        for year in range(start_year, end_year + 1):
            result = get_piotroski_from_db(company, year)
            conf = compute_piotroski_confidence(result["max_possible"])
            trend_data.append({
                "year": year,
                "score": result["total_score"],
                "max_possible": result["max_possible"],
                "confidence": conf,
            })
            reasoning += (
                f" -> {year}: score={result['total_score']}/{result['max_possible']}"
            )

        direction = classify_piotroski_trend(trend_data)

        # Confidence = min of yearly confidences, scaled by data coverage
        valid_entries = [d for d in trend_data if d["score"] is not None]
        if valid_entries:
            base_confidence = min(d["confidence"] for d in valid_entries)
            coverage = len(valid_entries) / len(trend_data)
            confidence = round(max(0.2, base_confidence * coverage), 2)
        else:
            confidence = 0.2

        confidence_label = (
            "high" if confidence >= 0.8
            else "medium" if confidence >= 0.5
            else "low"
        )

        explanation = build_piotroski_trend_explanation(
            company, trend_data, direction, year_range
        )

        trend_answer = {
            "company": company,
            "trend": [
                {"year": d["year"], "score": d["score"]}
                for d in trend_data
            ],
            "direction": direction,
            "explanation": explanation,
            "confidence": confidence,
            "confidence_label": confidence_label,
        }

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": trend_answer,
            "used_aggregation": False,
            "is_derived": False,
            "is_piotroski": True,
            "is_piotroski_trend": True,
            "missing_components": not valid_entries,
            "is_comparison": False,
            "companies": [company],
            "intent": "piotroski_trend",
            "metric": "piotroski_f_score",
            "year": end_year,
            "confidence": confidence,
        }

    def handle_risk_flags(
        self, company: str, year: int, reasoning: str
    ) -> Dict:
        """
        Evaluate deterministic financial risk flags for a single company/year.

        Calls build_risk_flags() which uses only existing DB helpers.
        No LLM reasoning, no new math.
        """
        if not company:
            return {
                "reasoning": reasoning + " -> no company identified for risk assessment",
                "used_bullets": [],
                "final_answer": None,
                "used_aggregation": False,
                "is_derived": False,
                "is_piotroski": False,
                "is_piotroski_trend": False,
                "is_risk_flags": True,
                "missing_components": True,
                "is_comparison": False,
                "companies": [],
                "intent": "risk_flags",
                "metric": None,
                "year": year,
                "confidence": 0.2,
            }

        result = build_risk_flags(company, year)
        explanation = build_risk_explanation(result)
        confidence = result["confidence"]
        confidence_label = (
            "high" if confidence >= 0.8
            else "medium" if confidence >= 0.5
            else "low"
        )

        risk_answer = {
            "company": company,
            "year": year,
            "risk_flags": result["risk_flags"],
            "explanation": explanation,
            "confidence": confidence,
            "confidence_label": confidence_label,
        }

        reasoning += (
            f" -> evaluated {result['evaluated_rules']}/6 risk rules,"
            f" found {len(result['risk_flags'])} flag(s)"
        )

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": risk_answer,
            "used_aggregation": False,
            "is_derived": False,
            "is_piotroski": False,
            "is_piotroski_trend": False,
            "is_risk_flags": True,
            "missing_components": result["evaluated_rules"] == 0,
            "is_comparison": False,
            "companies": [company],
            "intent": "risk_flags",
            "metric": None,
            "year": year,
            "confidence": confidence,
        }


class Reflector:
    """Compares prediction vs. ground truth to extract insights."""
    def reflect(self, prediction: Dict, ground_truth: str) -> Dict:
        try:
            pred_val = float(prediction["final_answer"])
            gt_val = float(ground_truth)
            correct = abs(pred_val - gt_val) < 1e-6
        except (TypeError, ValueError):
            correct = False

        key_insight = (
            "Check calculation accuracy"
            if not correct else
            "Consistent reasoning"
        )

        return {
            "correct": correct,
            "key_insight": key_insight,
            "tags": ["helpful" if correct else "harmful"]
        }

class Curator:
    """Updates the playbook with new insights."""
    def curate(self, playbook: List[str], reflection: Dict) -> List[str]:
        if reflection["key_insight"] not in playbook:
            playbook.append(reflection["key_insight"])
        return playbook

# ----------------------------
# Database Helpers
# ----------------------------
def compute_confidence(*, is_derived: bool, used_aggregation: bool, missing_components: bool) -> float:
    confidence = 1.0

    if used_aggregation:
        confidence -= 0.1

    if is_derived:
        confidence -= 0.3

    if missing_components:
        confidence -= 0.4

    # Enforce minimum confidence floor
    return round(max(0.2, confidence), 2)

def analyze_trend(metric: str, years: list[int], company) -> dict:
    """
    Analyze multi-year trend for a metric.
    Returns values + trend direction.
    """
    values = []

    for year in years:
        val = get_canonical_financial_fact(metric, year, company)
        if val is not None:
            values.append((year, val))

    if len(values) < 2:
        return {
            "values": values,
            "trend": "insufficient data"
        }

    diffs = [values[i+1][1] - values[i][1] for i in range(len(values)-1)]

    if all(d > 0 for d in diffs):
        trend = "increasing"
    elif all(d < 0 for d in diffs):
        trend = "decreasing"
    else:
        trend = "mixed"

    return {
        "values": values,
        "trend": trend
    }

def get_db_connection():
    import ace_research.db as _db
    return sqlite3.connect(_db.DB_PATH)

def infer_companies(question: str, available_companies: list[str]) -> list[str]:
    q = question.lower()
    found = []

    for company in available_companies:
        if company.lower() in q:
            found.append(company)

    return found

def get_ground_truth(metric: str, year: int = 2023) -> str:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM financial_facts WHERE metric = ? AND year = ?",
        (metric, year)
    )
    row = cur.fetchone()
    conn.close()
    return str(row[0]) if row else None


def store_prediction(question, prediction, confidence):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_predictions (question, predicted_answer, confidence) VALUES (?, ?, ?)",
        (question, prediction, confidence)
    )
    prediction_id = cur.lastrowid
    conn.commit()
    conn.close()
    return prediction_id


def store_feedback(prediction_id, correct_answer, is_correct):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_feedback VALUES (?, ?, ?)",
        (prediction_id, correct_answer, is_correct)
    )
    conn.commit()
    conn.close()


def update_playbook(rule):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO agent_playbook (rule) VALUES (?)",
        (rule,)
    )
    conn.commit()
    conn.close()

def summarize_confidence_trends(rows):
    total = len(rows)
    avg_conf = sum(r[1] for r in rows if r[1] is not None) / total

    by_metric = {}
    for q, conf, _ in rows:
        metric = q.lower().split(" is ")[-1]
        by_metric.setdefault(metric, []).append(conf)

    print(f"\nAverage confidence overall: {round(avg_conf, 2)}")
    print("\nConfidence by metric:")
    for metric, vals in by_metric.items():
        print(metric, "→", round(sum(vals)/len(vals), 2))
        if min(vals) < 0.5:
            print("⚠️ Unstable metric detected:", metric)

def compare_canonical_fact(metric: str, year: int, companies: list[str]):
    values = {}

    for company in companies:
        val = get_canonical_financial_fact(metric, year, company)
        if val is not None:
            values[company] = val

    if len(values) < 2:
        return {
            "values": values,
            "winner": None,
            "reason": "insufficient data"
        }

    sorted_vals = sorted(values.items(), key=lambda x: x[1], reverse=True)
    winner, winner_val = sorted_vals[0]
    runner_up, runner_val = sorted_vals[1]

    return {
        "values": values,
        "winner": winner,
        "delta": winner_val - runner_val,
        "ratio": winner_val / runner_val if runner_val != 0 else None
    }

def get_piotroski_from_db(company: str, year: int) -> dict:
    """
    Retrieve Piotroski F-Score from derived_metrics if cached.
    If not cached, compute, persist, and return.

    Implements Option C: never recompute if stored values exist.
    Returns dict identical in shape to compute_piotroski_score().
    """
    rows = get_derived_metrics_by_prefix("piotroski_", year, company)

    # Look for the total score row to confirm cache hit
    total_row = None
    signal_rows = {}
    for metric, value, input_components in rows:
        if metric == "piotroski_f_score":
            total_row = (value, input_components)
        else:
            signal_rows[metric] = (value, input_components)

    if total_row is not None:
        # Cache hit: reconstruct from stored data
        total_provenance = json.loads(total_row[1])

        signals = {}
        for metric, (value, input_components) in signal_rows.items():
            provenance = json.loads(input_components)
            signal_name = provenance["signal"]
            signals[signal_name] = {
                "signal": signal_name,
                "score": int(value) if value is not None else None,
                "value": provenance.get("raw_value"),
                "inputs": provenance.get("inputs", {}),
            }

        return {
            "company": company,
            "year": year,
            "total_score": int(total_row[0]) if total_row[0] is not None else None,
            "max_possible": total_provenance.get("max_possible", 0),
            "signals": signals,
        }

    # Cache miss: compute, persist, return
    return persist_piotroski_score(company, year)


def compute_piotroski_confidence(max_possible: int) -> float:
    """
    Piotroski-specific confidence based on how many of 9 signals were computable.

    - High (0.95): >= 8 signals computable
    - Medium (0.7): 5-7 signals computable
    - Low (0.4): 1-4 signals computable
    - Floor (0.2): 0 signals computable
    """
    if max_possible >= 8:
        return 0.95
    elif max_possible >= 5:
        return 0.7
    elif max_possible > 0:
        return 0.4
    else:
        return 0.2


def build_piotroski_explanation(result: dict) -> str:
    """
    Template-based Piotroski explanation. Deterministic, no LLM.
    Mentions strengths (score=1), weaknesses (score=0), and missing signals.
    """
    company = result["company"]
    year = result["year"]
    total = result["total_score"]
    max_possible = result["max_possible"]
    signals = result["signals"]

    if total is None:
        return f"Insufficient data to compute Piotroski F-Score for {company} in {year}."

    parts = [
        f"{company}'s Piotroski F-Score for {year} is {total}"
        f" out of {max_possible} computable signals (9 total)."
    ]

    strengths = sorted(name for name, sig in signals.items() if sig["score"] == 1)
    weaknesses = sorted(name for name, sig in signals.items() if sig["score"] == 0)
    missing = sorted(name for name, sig in signals.items() if sig["score"] is None)

    if strengths:
        parts.append("Strengths: " + ", ".join(s.replace("_", " ") for s in strengths) + ".")
    if weaknesses:
        parts.append("Weaknesses: " + ", ".join(s.replace("_", " ") for s in weaknesses) + ".")
    if missing:
        parts.append("Missing data for: " + ", ".join(s.replace("_", " ") for s in missing) + ".")

    if total >= 7:
        parts.append("This indicates strong financial health.")
    elif total >= 4:
        parts.append("This indicates moderate financial health.")
    else:
        parts.append("This indicates weak financial health.")

    return " ".join(parts)


def build_piotroski_comparison_explanation(ranking: list, year: int, winner) -> str:
    """
    Template-based explanation for multi-company Piotroski comparison.
    Deterministic, no LLM. Never invents numbers.
    """
    score_parts = []
    for entry in ranking:
        score = entry["score"]
        if score is not None:
            score_parts.append(f"{entry['company']} scored {score}/{entry['max_possible']}")
        else:
            score_parts.append(f"{entry['company']} has insufficient data")

    parts = [f"Comparing Piotroski F-Scores for {year}: {', '.join(score_parts)}."]

    if winner:
        parts.append(f"{winner} has the highest score.")
    else:
        tied = [e for e in ranking if e["score"] is not None]
        if len(tied) >= 2 and tied[0]["score"] == tied[1]["score"]:
            tied_names = [e["company"] for e in tied if e["score"] == tied[0]["score"]]
            parts.append(f"{' and '.join(tied_names)} are tied at {tied[0]['score']}.")
        else:
            parts.append("No clear winner could be determined.")

    return " ".join(parts)


def extract_piotroski_year_range(question: str, default_end: int = 2023) -> tuple:
    """
    Extract year range from a Piotroski trend question.

    Handles: "from YYYY to YYYY", "last N years", "since YYYY",
    two explicit years, or defaults to 5-year range.
    """
    q = question.lower()

    # "from YYYY to YYYY"
    m = re.search(r"from\s+(20\d{2})\s+to\s+(20\d{2})", q)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # "last N years"
    m = re.search(r"last\s+(\d+)\s+years?", q)
    if m:
        n = int(m.group(1))
        explicit_years = [int(y) for y in re.findall(r"(20\d{2})", q)]
        end = max(explicit_years) if explicit_years else default_end
        return (end - n + 1, end)

    # "since YYYY"
    m = re.search(r"since\s+(20\d{2})", q)
    if m:
        start = int(m.group(1))
        other_years = [int(y) for y in re.findall(r"(20\d{2})", q) if int(y) != start]
        end = max(other_years) if other_years else default_end
        return (start, end)

    # Two or more explicit years
    years = [int(y) for y in re.findall(r"(20\d{2})", q)]
    if len(years) >= 2:
        return (min(years), max(years))

    # Default: 5-year range ending at the explicit year or default_end
    end = years[0] if years else default_end
    return (end - 4, end)


def classify_piotroski_trend(trend_data: list) -> str:
    """
    Classify Piotroski trend direction from multi-year data.

    Returns: "improving", "declining", "stable", or "insufficient data".
    Compares first and last non-None scores.
    """
    scored = [(d["year"], d["score"]) for d in trend_data if d["score"] is not None]

    if len(scored) < 2:
        return "insufficient data"

    first_score = scored[0][1]
    last_score = scored[-1][1]

    if last_score > first_score:
        return "improving"
    elif last_score < first_score:
        return "declining"
    else:
        return "stable"


def build_piotroski_trend_explanation(
    company: str, trend_data: list, direction: str, year_range: tuple
) -> str:
    """
    Template-based explanation for multi-year Piotroski trend.
    Deterministic, no LLM. Never invents numbers.

    Format:
        {company}'s Piotroski F-Score trend from {start} to {end}.
        Available years: 2021 (6), 2022 (7), 2023 (8).
        Missing years: 2019, 2020.
        Trend: improving (6 -> 8).
    """
    start, end = year_range

    scored = [d for d in trend_data if d["score"] is not None]
    missing = [d for d in trend_data if d["score"] is None]

    parts = [f"{company}'s Piotroski F-Score trend from {start} to {end}."]

    if scored:
        available_str = ", ".join(f"{d['year']} ({d['score']})" for d in scored)
        parts.append(f"Available years: {available_str}.")

    if missing:
        missing_str = ", ".join(str(d["year"]) for d in missing)
        parts.append(f"Missing years: {missing_str}.")

    if direction == "improving":
        parts.append(f"Trend: improving ({scored[0]['score']} -> {scored[-1]['score']}).")
    elif direction == "declining":
        parts.append(f"Trend: declining ({scored[0]['score']} -> {scored[-1]['score']}).")
    elif direction == "stable":
        parts.append(f"Trend: stable ({scored[0]['score']}).")
    else:
        parts.append("Trend: insufficient data.")

    return " ".join(parts)


def build_risk_flags(company: str, year: int) -> dict:
    """
    Evaluate 6 deterministic risk rules for a company in a given year.

    Rules:
      1. Piotroski score <= 3  → "Weak financial strength"
      2. ROA declining YoY     → "Profitability deteriorating"
      3. Gross margin declining → "Margin compression"
      4. Leverage increasing   → "Rising financial leverage"
      5. Liquidity declining   → "Liquidity weakening"
      6. CFO < Net Income      → "Low earnings quality"

    Uses only existing DB helpers. No new math.
    Confidence reflects how many of the 6 rules had sufficient data.
    """
    flags = []
    evaluated = 0

    # Rule 1: Piotroski score <= 3
    piotroski_result = get_piotroski_from_db(company, year)
    if piotroski_result["total_score"] is not None:
        evaluated += 1
        if piotroski_result["total_score"] <= 3:
            flags.append("Weak financial strength")

    # Rule 2: ROA (net_income / total_assets) declining YoY
    roa_cur = get_metric_ratio("net_income", "total_assets", year, company)
    roa_pri = get_metric_ratio("net_income", "total_assets", year - 1, company)
    if roa_cur is not None and roa_pri is not None:
        evaluated += 1
        if roa_cur < roa_pri:
            flags.append("Profitability deteriorating")

    # Rule 3: Gross margin (gross_profit / revenue) declining YoY
    gm_cur = get_metric_ratio("gross_profit", "revenue", year, company)
    gm_pri = get_metric_ratio("gross_profit", "revenue", year - 1, company)
    if gm_cur is not None and gm_pri is not None:
        evaluated += 1
        if gm_cur < gm_pri:
            flags.append("Margin compression")

    # Rule 4: Leverage (long_term_debt / total_assets) increasing YoY
    lev_cur = get_metric_ratio("long_term_debt", "total_assets", year, company)
    lev_pri = get_metric_ratio("long_term_debt", "total_assets", year - 1, company)
    if lev_cur is not None and lev_pri is not None:
        evaluated += 1
        if lev_cur > lev_pri:
            flags.append("Rising financial leverage")

    # Rule 5: Liquidity (current_assets / current_liabilities) declining YoY
    liq_cur = get_metric_ratio("current_assets", "current_liabilities", year, company)
    liq_pri = get_metric_ratio("current_assets", "current_liabilities", year - 1, company)
    if liq_cur is not None and liq_pri is not None:
        evaluated += 1
        if liq_cur < liq_pri:
            flags.append("Liquidity weakening")

    # Rule 6: CFO < Net Income (low earnings quality)
    cfo = get_canonical_financial_fact("operating_cash_flow", year, company)
    net_income = get_canonical_financial_fact("net_income", year, company)
    if cfo is not None and net_income is not None:
        evaluated += 1
        if cfo < net_income:
            flags.append("Low earnings quality")

    # Confidence based on how many rules could be evaluated
    if evaluated >= 5:
        confidence = 0.9
    elif evaluated >= 3:
        confidence = 0.65
    elif evaluated >= 1:
        confidence = 0.4
    else:
        confidence = 0.2

    return {
        "company": company,
        "year": year,
        "risk_flags": flags,
        "evaluated_rules": evaluated,
        "confidence": confidence,
    }


def build_risk_explanation(result: dict) -> str:
    """
    Template-based explanation for risk flag assessment.
    Deterministic, no LLM.
    """
    company = result["company"]
    year = result["year"]
    flags = result["risk_flags"]
    evaluated = result["evaluated_rules"]

    if evaluated == 0:
        return (
            f"Insufficient data to evaluate financial risks for {company} in {year}."
        )

    parts = [
        f"Financial risk assessment for {company} in {year}"
        f" ({evaluated}/6 rules evaluated):"
    ]

    if not flags:
        parts.append("No risk flags detected.")
    else:
        parts.append(
            f"{len(flags)} risk flag(s) detected: {', '.join(sorted(flags))}."
        )

    return " ".join(parts)


def format_answer_with_confidence(answer, confidence):
    return {
        "answer": answer,
        "confidence": round(confidence, 2),
        "confidence_label": (
            "high" if confidence >= 0.8
            else "medium" if confidence >= 0.5
            else "low"
        )
    }

def verbalize_answer(answer_dict):
    label = answer_dict["confidence_label"]
    answer = answer_dict["answer"]

    if label == "high":
        return f"{answer}"
    elif label == "medium":
        return f"It appears that {answer}"
    else:
        return f"I'm not fully confident, but the best estimate is {answer}"

def format_numeric_answer(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        # Use commas + reasonable precision
        if abs(value) >= 1_000:
            return f"{value:,.0f}"
        else:
            return round(value, 4)

    return value

def build_explanation(prediction: dict) -> str:
    """
    Build a short, human-readable explanation for the answer.
    """
    parts = []

    intent = prediction.get("intent")
    metric = prediction.get("metric")
    companies = prediction.get("companies", [])
    year = prediction.get("year")

    if intent == "base_metric":
        parts.append(
            f"I retrieved the reported {metric.replace('_', ' ')}"
            f"{' for ' + companies[0] if companies else ''}"
            f"{' in ' + str(year) if year else ''}."
        )

    elif intent == "derived_metric":
        parts.append(
            f"I calculated {metric.replace('_', ' ')} using its underlying financial components."
        )

    elif intent == "trend":
        parts.append(
            f"I analyzed how {metric.replace('_', ' ')} changed over time."
        )

    elif intent == "comparison":
        parts.append(
            f"I compared {metric.replace('_', ' ')} across companies."
        )

    elif intent == "piotroski":
        parts.append(
            f"I retrieved the Piotroski F-Score"
            f"{' for ' + companies[0] if companies else ''}"
            f"{' in ' + str(year) if year else ''}."
        )

    elif intent == "piotroski_comparison":
        parts.append(
            f"I compared Piotroski F-Scores across"
            f" {', '.join(companies)}"
            f"{' in ' + str(year) if year else ''}."
        )

    elif intent == "piotroski_trend":
        trend_answer = prediction.get("final_answer") or {}
        start = trend_answer.get("trend", [{}])[0].get("year", "")
        end = trend_answer.get("trend", [{}])[-1].get("year", "") if trend_answer.get("trend") else ""
        parts.append(
            f"I analyzed the Piotroski F-Score trend"
            f"{' for ' + companies[0] if companies else ''}"
            f"{' from ' + str(start) + ' to ' + str(end) if start and end else ''}."
        )

    elif intent == "risk_flags":
        risk_answer = prediction.get("final_answer") or {}
        flag_count = len(risk_answer.get("risk_flags", []))
        parts.append(
            f"I assessed financial risk signals"
            f"{' for ' + companies[0] if companies else ''}"
            f"{' in ' + str(year) if year else ''}."
            + (
                f" Found {flag_count} risk flag(s)."
                if flag_count > 0
                else " No risk flags detected."
            )
        )

    confidence = prediction.get("confidence", 0)
    if confidence >= 0.8:
        parts.append("The data supporting this answer is complete and consistent.")
    elif confidence >= 0.5:
        parts.append("Some assumptions were required, which introduces moderate uncertainty.")
    else:
        parts.append("The available data is incomplete, so this answer is uncertain.")

    return " ".join(parts)

# ----------------------------
# ACE Simulation
# ----------------------------

def simulate_ace(samples: List[Dict], initial_playbook: List[str]):
    generator = Generator(initial_playbook)
    reflector = Reflector()
    curator = Curator()

    playbook = initial_playbook.copy()

    for sample in samples:
        question = sample["question"] 
        year = sample.get("year", 2023)

        metric = sample["metric"]
        is_derived = metric in derived_metrics
        is_piotroski = metric == "piotroski_f_score"
        gt = None
        if not is_derived and not is_piotroski:
            gt = get_ground_truth(metric, year)

        # Step 1: Generate
        prediction = generator.generate(question)

        # Use structured confidence when available (Piotroski / risk flags)
        if (prediction.get("is_piotroski") or prediction.get("is_risk_flags")) and "confidence" in prediction:
            confidence = prediction["confidence"]
        else:
            confidence = compute_confidence(
                is_derived=prediction["is_derived"],
                used_aggregation=prediction["used_aggregation"],
                missing_components=prediction["missing_components"]
            )

        formatted_answer = format_numeric_answer(prediction["final_answer"])

        spoken_answer = format_answer_with_confidence(
            answer = formatted_answer,
            confidence=confidence
        )

        spoken_answer["explanation"] = build_explanation({
            **prediction,
            "confidence": confidence
        })

        serialized_answer = json.dumps(spoken_answer)

        # Piotroski / risk flags: store and continue (no ground truth to compare)
        if prediction.get("is_piotroski") or prediction.get("is_risk_flags"):
            prediction_id = store_prediction(question, serialized_answer, confidence)
            store_feedback(prediction_id, None, 1)
            continue

        # Store unknown metric for learning instead of stopping with ValueError
        if gt is None and not is_derived:
            prediction_id = store_prediction(question, serialized_answer, confidence)
            store_feedback(prediction_id, None, 0)

            insight = f"Metric '{sample['metric']}' requires derivation or is unsupported"

            reflection = {
                "correct": False,
                "key_insight": insight
            }
            playbook = curator.curate(playbook, reflection)
            generator.playbook = playbook
            update_playbook(insight)
            continue

        if is_derived:
            prediction_id = store_prediction(question, serialized_answer, confidence)
            store_feedback(prediction_id, None, 1)  # mark as successful execution
            continue
        
        # Step 2: Reflect
        reflection = reflector.reflect(prediction, gt)

        # Step 3: Curate (update playbook)
        playbook = curator.curate(playbook, reflection)
        generator.playbook = playbook

        prediction_id = store_prediction(question, serialized_answer, confidence)
        store_feedback(prediction_id, gt, int(reflection["correct"]))

        if not reflection["correct"]:
            update_playbook(reflection["key_insight"])

def print_confidence_trends():
    rows = get_confidence_history()

    if not rows:
        print("No confidence data found.")
        return

    metric_confidence = defaultdict(list)

    for question, confidence, *_ in rows:
        q = question.lower()
        if "revenue" in q:
            metric_confidence["revenue"].append(confidence)
        elif "net income" in q:
            metric_confidence["net_income"].append(confidence)
        elif "operating margin" in q:
            metric_confidence["operating_margin"].append(confidence)
        else:
            metric_confidence["other"].append(confidence)

    print("\n=== Confidence Trend Summary ===")
    for metric, values in metric_confidence.items():
        avg = round(sum(values) / len(values), 3)
        print(f"{metric}: avg={avg}, min={min(values)}, max={max(values)}")

# ----------------------------
# Example Run
# ----------------------------

if __name__ == "__main__":
    mock_samples = [
    # Trend questions (often mixed or insufficient data)
    {
        "question": "What is the trend of Microsoft's revenue?",
        "metric": "revenue"
    },
    {
        "question": "How has Google's net income changed over time?",
        "metric": "net_income"
    },
    {
        "question": "Is Microsoft's operating income increasing or decreasing?",
        "metric": "operating_income"
    },
    {
        "question": "What is the trend of Google's gross margin?",
        "metric": "gross_margin"
    },
    {
        "question": "How has Microsoft's return on equity changed over time?",
        "metric": "return_on_equity"
    },
    {
        "question": "Is Google's asset turnover increasing or decreasing?",
        "metric": "asset_turnover"
    },
    {
        "question": "What is the trend of Microsoft's current ratio?",
        "metric": "current_ratio"
    },

    # Ambiguous / underspecified year
    {
        "question": "What is Microsoft's revenue?",
        "metric": "revenue"
    },
    {
        "question": "What is Google's net income?",
        "metric": "net_income"
    },

    # Years outside ingested coverage
    {
        "question": "What was Microsoft's revenue in 2018?",
        "metric": "revenue"
    },
    {
        "question": "What was Google's operating income in 2019?",
        "metric": "operating_income"
    },

    # Derived metrics with partial or missing components
    {
        "question": "What is Microsoft's EBITDA margin for 2016?",
        "metric": "ebitda_margin"
    },
    {
        "question": "What is Google's net margin for 2015?",
        "metric": "net_margin"
    },
    {
        "question": "What is Microsoft's operating margin for 2023?",
        "metric": "operating_margin"
    },
    {
        "question": "What is Google's gross margin?",
        "metric": "gross_margin"
    },
    {
        "question": "What is Microsoft's return on assets for 2022?",
        "metric": "return_on_assets"
    },
    {
        "question": "What is Google's return on equity?",
        "metric": "return_on_equity"
    },
    {
        "question": "What is Microsoft's debt to equity ratio for 2023?",
        "metric": "debt_to_equity"
    },
    {
        "question": "What is Google's current ratio?",
        "metric": "current_ratio"
    },
    {
        "question": "What is Microsoft's asset turnover for 2022?",
        "metric": "asset_turnover"
    },
    {
        "question": "What is Google's debt ratio?",
        "metric": "debt_ratio"
    },
    {
        "question": "What is Microsoft's equity ratio for 2023?",
        "metric": "equity_ratio"
    },
    {
        "question": "What is Google's equity multiplier?",
        "metric": "equity_multiplier"
    },
    {
        "question": "What is Microsoft's return on invested capital for 2022?",
        "metric": "return_on_invested_capital"
    },

    # Comparison with weak overlap
    {
        "question": "Compare Microsoft and Google revenue trends",
        "metric": "revenue"
    },
    {
        "question": "Which company had better profitability over time, Microsoft or Google?",
        "metric": "net_income"
    },
    {
        "question": "Compare Microsoft and Google operating margins",
        "metric": "operating_margin"
    },
    {
        "question": "Which company has a better return on assets, Microsoft or Google?",
        "metric": "return_on_assets"
    },
    {
        "question": "Compare the debt to equity ratios of Microsoft and Google",
        "metric": "debt_to_equity"
    },

    # Vague aggregation intent (unsupported or unclear)
    {
        "question": "What is the average revenue of Microsoft?",
        "metric": "revenue"
    },
    {
        "question": "What is the median net income of Google?",
        "metric": "net_income"
    },

    # Balance sheet items that may be missing or inconsistent
    {
        "question": "What are Microsoft's total assets for 2022?",
        "metric": "total_assets"
    },

    # Piotroski F-Score queries
    {
        "question": "What is Microsoft's Piotroski score in 2023?",
        "metric": "piotroski_f_score"
    },
    {
        "question": "How strong is Microsoft's F-score?",
        "metric": "piotroski_f_score"
    },

    # Piotroski comparison queries
    {
        "question": "Compare Microsoft and Google by Piotroski score in 2023",
        "metric": "piotroski_f_score"
    },

    # Piotroski trend queries
    {
        "question": "Show Microsoft's Piotroski trend from 2019 to 2023",
        "metric": "piotroski_f_score"
    },
    {
        "question": "Has Microsoft's financial strength improved over the last 5 years?",
        "metric": "piotroski_f_score"
    },

    # Risk flag queries
    {
        "question": "Are there any financial risks for Microsoft in 2023?",
        "metric": "risk_flags"
    },
    {
        "question": "What warning signs does Google show in 2023?",
        "metric": "risk_flags"
    },
]
    initial_playbook = ["Always read financial note disclosures carefully."]
    simulate_ace(mock_samples, initial_playbook)
    print_confidence_trends()
