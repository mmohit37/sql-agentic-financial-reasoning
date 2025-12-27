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
from db import get_available_aggregations, get_available_metrics, get_confidence_history
from db import query_financial_fact, query_aggregate

derived_metrics = {
    "operating_margin": {
        "formula": "operating_income / revenue",
        "components": ["operating_income", "revenue"]
    }
}

# ----------------------------
# Agentic Roles
# ----------------------------

class Generator:
    """Produces reasoning and answers using a playbook."""
    def __init__(self, playbook: List[str]):
        self.playbook = playbook

    def generate(self, question: str) -> Dict:
        reasoning = f"Interpreting the question: {question}"
        
        q = question.lower()

        # Identify complex metric
        for derived, spec in derived_metrics.items():
            if derived.replace("_", " ") in q:
                reasoning += f" → identified derived metric: {derived}"
                return self.compute_derived_metric(derived, spec, q, reasoning)

        years = re.findall(r"(20\d{2})", q)
        year = int(years[0]) if years else 2023
        reasoning += f" → inferred year={year}"
        
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
        
        if requested_agg and requested_agg not in available_aggs:
            return {
                "reasoning": reasoning + f" → aggregation '{requested_agg}' not supported by schema",
                "used_bullets": [],
                "final_answer": None,
                "used_aggregation": False,
                "is_derived": False,
                "missing_components": True
            }
        
        if agg:
            value = query_aggregate(metric, agg, year)
        else:
            value = query_financial_fact(metric, year)
            reasoning += f" → querying SQL for ({metric}, {year})"

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": str(value),
            "used_aggregation": agg is not None,
            "is_derived": False,
            "missing_components": value is None
        }
    
    def compute_derived_metric(self, name, spec, q, reasoning):
        # Infer year
        years = re.findall(r"(20\d{2})", q)
        year = int(years[0]) if years else 2023
        reasoning += f" → inferred year={year}"

        values = {}

        for component in spec["components"]:
            val = query_financial_fact(component, year)
            if val is None:
                reasoning += f" → missing component: {component}"
                return {
                    "reasoning": reasoning,
                    "used_bullets": [],
                    "final_answer": None,
                    "used_aggregation": False,
                    "is_derived": True,
                    "missing_components": True
                }
            values[component] = val
            reasoning += f" → fetched {component}={val}"

        # Compute formula safely
        try:
            result = values["operating_income"] / values["revenue"]
            reasoning += f" → computed {name} = {result}"
        except ZeroDivisionError:
            result = None
            reasoning += " → division by zero error"

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": str(round(result, 4)) if result is not None else None,
            "used_aggregation": False,
            "is_derived": True,
            "missing_components": False
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



def get_db_connection():
    return sqlite3.connect("../sql_course/agent.db")


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

        # Store unknown metric for learning instead of stopping with ValueError
        if gt is None and not is_derived:
            store_prediction(question, None, confidence)
            store_feedback(None, None, 0)

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
            prediction_id = store_prediction(question, prediction["final_answer"], confidence)
            store_feedback(prediction_id, None, 1)  # mark as successful execution
            continue
        
        # Step 2: Reflect
        reflection = reflector.reflect(prediction, gt)

        # Step 3: Curate (update playbook)
        playbook = curator.curate(playbook, reflection)
        generator.playbook = playbook

        prediction_id = store_prediction(question, prediction["final_answer"], confidence)
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
        {"question": "What is revenue for 2023?", "metric": "revenue"},
        {"question": "What is the median revenue for 2023?", "metric": "revenue"},
        {"question": "What is the average net income for 2023?", "metric": "net_income"},
        {"question": "What is operating margin for 2023?", "metric": "operating_margin"},
        {"question": "What is EBITDA for 2023?", "metric": "ebitda"}
    ]
    initial_playbook = ["Always read financial note disclosures carefully."]
    simulate_ace(mock_samples, initial_playbook)
    print_confidence_trends()
