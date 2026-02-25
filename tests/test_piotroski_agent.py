"""
Tests for Piotroski F-Score agent integration.

Verifies:
1. Intent detection for Piotroski keywords
2. get_piotroski_from_db() cache-hit and cache-miss paths
3. Piotroski confidence logic
4. Template-based explanation generation
5. Generator.generate() end-to-end for Piotroski questions
6. Structured response shape
7. Determinism: identical results across runs
"""

import pytest
import sqlite3
import tempfile
import os
import json


@pytest.fixture
def piotroski_db():
    """
    Create a temp database with financial_facts + derived_metrics,
    populated with two years of data for Microsoft (matching test_piotroski.py pattern).

    Expected Piotroski total: 8 / 9  (same as TestCo in test_piotroski.py)
    """
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            UNIQUE(company, year, metric)
        )
    """)

    cur.execute("""
        CREATE TABLE derived_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            metric_type TEXT NOT NULL,
            input_components TEXT NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, year, metric)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            predicted_answer TEXT,
            confidence REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_feedback (
            prediction_id INTEGER,
            correct_answer TEXT,
            is_correct INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_playbook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule TEXT UNIQUE
        )
    """)

    # Year 2022 (prior year)
    data_2022 = [
        ("Microsoft", 2022, "net_income", 90000.0),
        ("Microsoft", 2022, "total_assets", 900000.0),
        ("Microsoft", 2022, "operating_cash_flow", 120000.0),
        ("Microsoft", 2022, "long_term_debt", 350000.0),
        ("Microsoft", 2022, "current_assets", 300000.0),
        ("Microsoft", 2022, "current_liabilities", 180000.0),
        ("Microsoft", 2022, "shares_outstanding", 1000.0),
        ("Microsoft", 2022, "gross_profit", 500000.0),
        ("Microsoft", 2022, "revenue", 800000.0),
    ]

    # Year 2023 (current year)
    data_2023 = [
        ("Microsoft", 2023, "net_income", 150000.0),
        ("Microsoft", 2023, "total_assets", 1000000.0),
        ("Microsoft", 2023, "operating_cash_flow", 200000.0),
        ("Microsoft", 2023, "long_term_debt", 300000.0),
        ("Microsoft", 2023, "current_assets", 400000.0),
        ("Microsoft", 2023, "current_liabilities", 200000.0),
        ("Microsoft", 2023, "shares_outstanding", 1000.0),
        ("Microsoft", 2023, "gross_profit", 600000.0),
        ("Microsoft", 2023, "revenue", 1000000.0),
    ]

    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        data_2022 + data_2023,
    )

    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    yield db_path

    db_module.DB_PATH = original
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def cached_piotroski_db(piotroski_db):
    """
    Same as piotroski_db, but with Piotroski results pre-persisted.
    This tests the cache-hit path.
    """
    from ace_research.piotroski import persist_piotroski_score

    persist_piotroski_score("Microsoft", 2023)
    return piotroski_db


# ============================================================
# Intent Detection
# ============================================================

def test_intent_detection_piotroski_keyword(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What is Microsoft's Piotroski score in 2023?")

    assert plan["intent"] == "piotroski"
    assert plan["is_piotroski"] is True
    assert plan["metric"] == "piotroski_f_score"
    assert "Microsoft" in plan["companies"]
    assert plan["year"] == 2023


def test_intent_detection_f_score_keyword(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("How strong is Microsoft's F-score?")

    assert plan["intent"] == "piotroski"
    assert plan["is_piotroski"] is True


def test_intent_detection_financial_strength(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What is the financial strength score for Microsoft in 2023?")

    assert plan["intent"] == "piotroski"


def test_non_piotroski_intent_unchanged(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What is Microsoft's revenue in 2023?")

    assert plan["intent"] != "piotroski"
    assert plan.get("is_piotroski") is False


# ============================================================
# get_piotroski_from_db: cache miss
# ============================================================

def test_cache_miss_computes_and_persists(piotroski_db):
    from ace_research.experiments import get_piotroski_from_db

    result = get_piotroski_from_db("Microsoft", 2023)

    assert result["company"] == "Microsoft"
    assert result["year"] == 2023
    assert result["total_score"] == 8
    assert result["max_possible"] == 9
    assert len(result["signals"]) == 9

    # Verify it was persisted
    conn = sqlite3.connect(piotroski_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM derived_metrics WHERE company='Microsoft' AND year=2023"
    )
    count = cur.fetchone()[0]
    conn.close()
    assert count == 10  # 9 signals + 1 total


# ============================================================
# get_piotroski_from_db: cache hit
# ============================================================

def test_cache_hit_returns_stored_values(cached_piotroski_db):
    from ace_research.experiments import get_piotroski_from_db

    result = get_piotroski_from_db("Microsoft", 2023)

    assert result["company"] == "Microsoft"
    assert result["year"] == 2023
    assert result["total_score"] == 8
    assert result["max_possible"] == 9
    assert len(result["signals"]) == 9

    # Verify each signal has correct structure
    for name, sig in result["signals"].items():
        assert "signal" in sig
        assert "score" in sig
        assert "value" in sig
        assert "inputs" in sig


def test_cache_hit_no_recomputation(cached_piotroski_db):
    """Two calls should return identical results without recomputing."""
    from ace_research.experiments import get_piotroski_from_db

    result1 = get_piotroski_from_db("Microsoft", 2023)
    result2 = get_piotroski_from_db("Microsoft", 2023)

    assert result1["total_score"] == result2["total_score"]
    assert result1["max_possible"] == result2["max_possible"]

    for name in result1["signals"]:
        assert result1["signals"][name]["score"] == result2["signals"][name]["score"]


# ============================================================
# Confidence Logic
# ============================================================

def test_confidence_high_all_signals():
    from ace_research.experiments import compute_piotroski_confidence

    assert compute_piotroski_confidence(9) == 0.95
    assert compute_piotroski_confidence(8) == 0.95


def test_confidence_medium():
    from ace_research.experiments import compute_piotroski_confidence

    assert compute_piotroski_confidence(7) == 0.7
    assert compute_piotroski_confidence(5) == 0.7


def test_confidence_low():
    from ace_research.experiments import compute_piotroski_confidence

    assert compute_piotroski_confidence(4) == 0.4
    assert compute_piotroski_confidence(1) == 0.4


def test_confidence_floor():
    from ace_research.experiments import compute_piotroski_confidence

    assert compute_piotroski_confidence(0) == 0.2


# ============================================================
# Explanation Template
# ============================================================

def test_explanation_mentions_strengths_and_weaknesses(piotroski_db):
    from ace_research.experiments import get_piotroski_from_db, build_piotroski_explanation

    result = get_piotroski_from_db("Microsoft", 2023)
    explanation = build_piotroski_explanation(result)

    assert "Microsoft" in explanation
    assert "2023" in explanation
    assert "8" in explanation
    assert "Strengths:" in explanation
    assert "Weaknesses:" in explanation
    assert "moderate" in explanation or "strong" in explanation


def test_explanation_no_invented_numbers(piotroski_db):
    from ace_research.experiments import get_piotroski_from_db, build_piotroski_explanation

    result = get_piotroski_from_db("Microsoft", 2023)
    explanation = build_piotroski_explanation(result)

    # Should not contain numbers that aren't the score or year
    # Just verify it doesn't invent revenue/asset numbers
    assert "150000" not in explanation
    assert "1000000" not in explanation


def test_explanation_insufficient_data():
    from ace_research.experiments import build_piotroski_explanation

    result = {
        "company": "NoCo",
        "year": 2023,
        "total_score": None,
        "max_possible": 0,
        "signals": {},
    }
    explanation = build_piotroski_explanation(result)
    assert "Insufficient data" in explanation


# ============================================================
# Generator end-to-end
# ============================================================

def test_generate_piotroski_returns_structured_response(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("What is Microsoft's Piotroski score in 2023?")

    assert result.get("is_piotroski") is True
    assert result["intent"] == "piotroski"

    answer = result["final_answer"]
    assert answer is not None
    assert answer["company"] == "Microsoft"
    assert answer["year"] == 2023
    assert answer["piotroski_score"] == 8
    assert answer["max_score"] == 9
    assert len(answer["signals"]) == 9
    assert "explanation" in answer
    assert "confidence" in answer
    assert "confidence_label" in answer


def test_generate_piotroski_confidence_label(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("What is Microsoft's Piotroski score in 2023?")
    answer = result["final_answer"]

    # 9 signals computable -> high confidence
    assert answer["confidence"] == 0.95
    assert answer["confidence_label"] == "high"


def test_generate_piotroski_no_company(piotroski_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("What is the Piotroski score?")

    # No company identified -> missing_components True
    assert result["missing_components"] is True


def test_generate_piotroski_deterministic(piotroski_db):
    """Two identical queries produce identical results."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    r1 = gen.generate("What is Microsoft's Piotroski score in 2023?")
    r2 = gen.generate("What is Microsoft's Piotroski score in 2023?")

    assert r1["final_answer"]["piotroski_score"] == r2["final_answer"]["piotroski_score"]
    assert r1["final_answer"]["signals"] == r2["final_answer"]["signals"]
    assert r1["final_answer"]["explanation"] == r2["final_answer"]["explanation"]


# ============================================================
# simulate_ace integration
# ============================================================

def test_simulate_ace_stores_piotroski_prediction(piotroski_db):
    from ace_research.experiments import simulate_ace

    samples = [
        {
            "question": "What is Microsoft's Piotroski score in 2023?",
            "metric": "piotroski_f_score",
        }
    ]

    simulate_ace(samples, ["test rule"])

    # Verify prediction was stored
    conn = sqlite3.connect(piotroski_db)
    cur = conn.cursor()
    cur.execute("SELECT question, confidence FROM agent_predictions ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert "Piotroski" in row[0]
    assert row[1] == 0.95  # high confidence for 9 computable signals


# ============================================================
# get_derived_metrics_by_prefix (db helper)
# ============================================================

def test_get_derived_metrics_by_prefix_empty(piotroski_db):
    from ace_research.db import get_derived_metrics_by_prefix

    rows = get_derived_metrics_by_prefix("piotroski_", 2023, "Microsoft")
    assert rows == []  # nothing persisted yet


def test_get_derived_metrics_by_prefix_after_persist(cached_piotroski_db):
    from ace_research.db import get_derived_metrics_by_prefix

    rows = get_derived_metrics_by_prefix("piotroski_", 2023, "Microsoft")
    assert len(rows) == 10  # 9 signals + 1 total

    metrics = {row[0] for row in rows}
    assert "piotroski_f_score" in metrics
    assert "piotroski_roa_positive" in metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
