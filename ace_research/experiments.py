"""
experiments.py
Reproduction scaffold for ACE (Agentic Context Engineering) on FINER benchmark.
Simulates the three-agent workflow: Generator → Reflector → Curator.
"""

import json
from typing import List, Dict
import sqlite3

# ----------------------------
# Agentic Roles
# ----------------------------

class Generator:
    """Produces reasoning and answers using a playbook."""
    def __init__(self, playbook: List[str]):
        self.playbook = playbook

    def generate(self, question: str) -> Dict:
        reasoning = f"Step-by-step reasoning for: {question}"
        answer = "42"  # placeholder for predicted result
        return {
            "reasoning": reasoning,
            "used_bullets": [i for i in range(min(3, len(self.playbook)))],
            "final_answer": answer
        }

class Reflector:
    """Compares prediction vs. ground truth to extract insights."""
    def reflect(self, prediction: Dict, ground_truth: str) -> Dict:
        correct = prediction["final_answer"] == ground_truth
        key_insight = "Check calculation accuracy" if not correct else "Consistent reasoning"
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
        "INSERT INTO agent_playbook (rule) VALUES (?)",
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
        gt = get_ground_truth(sample["metric"])


        if gt is None:
            raise ValueError(f"No ground truth found for metric: {sample['metric']}")

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
        {"question": "What is total revenue for 2023?", "metric": "revenue"},
        {"question": "What is net income for 2023?", "metric": "net_income"}
    ]
    initial_playbook = ["Always read financial note disclosures carefully."]
    simulate_ace(mock_samples, initial_playbook)


# ----------------------------
# Mock FiNER Experiment
# ----------------------------
import random
import matplotlib.pyplot as plt

def simulate_finer_adaptation(rounds=10):
    """Simulate online context adaptation over multiple samples."""
    mock_samples = [
        {"question": "Revenue in Q1 2023?", "answer": "500"},
        {"question": "Operating income in 2023?", "answer": "200"},
        {"question": "Net income in 2023?", "answer": "150"},
        {"question": "Total liabilities in 2023?", "answer": "700"},
        {"question": "Earnings per share in 2023?", "answer": "2.1"},
        {"question": "Gross profit margin in 2022?", "answer": "0.48"},
        {"question": "Debt-to-equity ratio in 2023?", "answer": "1.5"},
        {"question": "Cash flow from operations?", "answer": "320"},
        {"question": "Total assets in 2023?", "answer": "1000"},
        {"question": "Interest expense in 2023?", "answer": "75"}
    ]

    generator = Generator(["Always verify financial disclosures."])
    reflector = Reflector()
    curator = Curator()
    playbook = generator.playbook.copy()

    accuracies = []

    for i in range(rounds):
        sample = random.choice(mock_samples)
        prediction = generator.generate(sample["question"])
        reflection = reflector.reflect(prediction, sample["answer"])
        playbook = curator.curate(playbook, reflection)
        correct_count = 1 if reflection["correct"] else 0
        accuracies.append(sum(accuracies[-3:]) / (len(accuracies[-3:]) + 1) + correct_count / 2)

    plt.plot(range(1, rounds + 1), accuracies, marker='o')
    plt.title("Simulated Online Adaptation Accuracy (FiNER-style)")
    plt.xlabel("Adaptation Round")
    plt.ylabel("Simulated Accuracy (normalized)")
    plt.grid(True)
    plt.show()

#if __name__ == "__main__":
#    simulate_finer_adaptation(rounds=12)