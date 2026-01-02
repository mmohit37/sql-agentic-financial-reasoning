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
from db import get_available_aggregations, get_available_metrics, get_confidence_history, get_available_years, get_available_companies
from db import query_aggregate, get_canonical_financial_fact

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
    }
}

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

        if is_trend:
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
            "metric": metric,
            "base_metrics": base_metrics,
            "companies": companies,
            "year": year,
            "is_trend": is_trend,
            "is_comparison": is_comparison,
            "is_derived": is_derived
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

            if is_comparison and not agg and not is_derived:
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
            value = results
        else:
            value = results[companies[0]]

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": str(value),
            "used_aggregation": agg is not None,
            "is_derived": False,
            "missing_components": (
                any(v is None for v in value.values())
                if is_comparison
                else value is None
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
    return sqlite3.connect("../sql_course/agent.db")

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

def compare_canonical_fact(metric: str, year: int, companies: list[str]) -> dict:
    """
    Compare a canonical metric across multiple companies.
    Returns values + winner.
    """
    results = {}

    for company in companies:
        val = get_canonical_financial_fact(metric, year, company)
        if val is not None:
            results[company] = val

    if len(results) < 2:
        return {
            "values": results,
            "winner": None,
            "status": "insufficient data"
        }

    winner = max(results, key=results.get)

    return {
        "values": results,
        "winner": winner,
        "status": "ok"
    }

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
        gt = None
        if not is_derived:
            gt = get_ground_truth(metric, year)

        # Step 1: Generate
        prediction = generator.generate(question)

        confidence = compute_confidence(
            is_derived=prediction["is_derived"],
            used_aggregation=prediction["used_aggregation"],
            missing_components=prediction["missing_components"]
        )

        spoken_answer = format_answer_with_confidence(
            answer = prediction["final_answer"],
            confidence=confidence
        )

        serialized_answer = json.dumps(spoken_answer)

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
    # --- Canonical single-year facts ---
    {"question": "What is Microsoft net income for 2021?", "metric": "net_income"},
    {"question": "What is Microsoft revenue for 2022?", "metric": "revenue"},
    {"question": "What is Microsoft operating income for 2023?", "metric": "operating_income"},

    # --- Derived single-year metrics ---
    {"question": "What is Microsoft operating margin for 2023?", "metric": "operating_margin"},
    {"question": "What is Microsoft net margin for 2022?", "metric": "net_margin"},
    {"question": "What is Microsoft EBITDA margin for 2015?", "metric": "ebitda_margin"},

    # --- Trend questions (canonical) ---
    {"question": "What is Microsoft revenue trend?", "metric": "revenue"},
    {"question": "How has Microsoft net income changed over time?", "metric": "net_income"},

    # --- Trend questions (derived) ---
    {"question": "What is Microsoft operating margin trend?", "metric": "operating_margin"},
    {"question": "How has Microsoft net margin changed over time?", "metric": "net_margin"},
]
    initial_playbook = ["Always read financial note disclosures carefully."]
    simulate_ace(mock_samples, initial_playbook)
    print_confidence_trends()
