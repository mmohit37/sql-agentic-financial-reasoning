"""
experiments.py
Reproduction scaffold for ACE (Agentic Context Engineering) on FINER benchmark.
Simulates the three-agent workflow: Generator → Reflector → Curator.
"""

import json
from typing import List, Dict
import sqlite3
import re
from db import query_financial_fact, query_aggregate

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

        years = re.findall(r"(20\d{2})", q)
        year = int(years[0]) if years else 2023
        reasoning += f" → inferred year={year}"
        
        if "revenue" in q:
            metric = "revenue"
        elif "net income" in q:
            metric = "net_income"
        else:
            return {
                "reasoning": "Metric not recognized",
                "used_bullets": [],
                "final_answer": None
            }

        aggregation_map = {
            "total": "SUM",
            "average": "AVG",
            "sum": "SUM",
            "avg": "AVG",
            "mean": "AVG",
            "max": "MAX",
            "min": "MIN",
            "count": "COUNT",
        }

        agg = None
        for keyword, sql_agg in aggregation_map.items():
            if keyword in q:
                agg = sql_agg
                reasoning += f" → Using SQL {sql_agg} aggregation on {metric}"
                break
        
        if agg:
            value = query_aggregate(metric, agg, year)
        else:
            value = query_financial_fact(metric, year)
            reasoning += f" → querying SQL for ({metric}, {year})"

        return {
            "reasoning": reasoning,
            "used_bullets": list(range(min(3, len(self.playbook)))),
            "final_answer": str(value)
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


def store_prediction(question, prediction):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_predictions (question, predicted_answer) VALUES (?, ?)",
        (question, prediction)
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
        gt = get_ground_truth(sample["metric"], year)

        # Store unknown metric for learning instead of stopping with ValueError
        if gt is None:
            store_prediction(question, None)
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
        
        # Step 1: Generate
        prediction = generator.generate(question)
        
        # Step 2: Reflect
        reflection = reflector.reflect(prediction, gt)

        # Step 3: Curate (update playbook)
        playbook = curator.curate(playbook, reflection)
        generator.playbook = playbook

        prediction_id = store_prediction(question, prediction["final_answer"])
        store_feedback(prediction_id, gt, int(reflection["correct"]))

        if not reflection["correct"]:
            update_playbook(reflection["key_insight"])
        

# ----------------------------
# Example Run
# ----------------------------

if __name__ == "__main__":
    mock_samples = [
        {"question": "What is revenue for 2023?", "metric": "revenue"},
        {"question": "What is total revenue for 2023?", "metric": "revenue"},
        {"question": "What is the average net income for 2023?", "metric": "net_income"},
        {"question": "What is the mean revenue for 2023?", "metric": "revenue"},
        {"question": "What is the max revenue for 2023?", "metric": "revenue"},
        {"question": "What is operating margin for 2023?", "metric": "operating_margin"},
    ]
    initial_playbook = ["Always read financial note disclosures carefully."]
    simulate_ace(mock_samples, initial_playbook)
