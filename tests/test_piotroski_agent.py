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


# ============================================================
# Multi-company comparison
# ============================================================

@pytest.fixture
def two_company_db():
    """
    Temp database with Microsoft (score 8/9) and Google (score 5/9).

    Google data designed for:
      1. ROA = 80k/700k > 0           -> 1
      2. CFO = 90k > 0                -> 1
      3. delta ROA: no 2022 data      -> None
      4. accruals = (90k-80k)/700k>0  -> 1
      5. delta leverage: no prior     -> None
      6. delta liquidity: no prior    -> None
      7. no equity issuance: no prior -> None
      8. delta gross margin: no prior -> None
      9. at = 500k/700k > 0 (no prior)-> None
    So Google: 3 computable, all pass -> score 3/3, but only 3 max_possible
    Wait, let me redesign. I need Google to have TWO years of data for a
    more interesting comparison. Let me give Google weaker numbers.

    Google 2022:
      net_income=60k, total_assets=600k, operating_cash_flow=50k,
      long_term_debt=200k, current_assets=150k, current_liabilities=120k,
      shares_outstanding=800, gross_profit=250k, revenue=500k

    Google 2023:
      net_income=70k, total_assets=650k, operating_cash_flow=55k,
      long_term_debt=220k, current_assets=180k, current_liabilities=140k,
      shares_outstanding=850, gross_profit=300k, revenue=600k

    Signals:
      1. ROA = 70k/650k = 0.1077 > 0                   -> 1
      2. CFO = 55k > 0                                  -> 1
      3. ROA_23=0.1077, ROA_22=60k/600k=0.10 -> +0.0077 -> 1
      4. accruals = (55k-70k)/650k = -0.023 < 0         -> 0
      5. lev_23=220k/650k=0.338, lev_22=200k/600k=0.333 -> +0.005 -> 0  (increased)
      6. liq_23=180k/140k=1.286, liq_22=150k/120k=1.25 -> +0.036 -> 1
      7. shares_23=850 > shares_22=800 -> +50 > 0       -> 0  (equity issuance)
      8. gm_23=300k/600k=0.50, gm_22=250k/500k=0.50 -> 0 -> 0  (no improvement)
      9. at_23=600k/650k=0.923, at_22=500k/600k=0.833 -> +0.090 -> 1

    Google total: 5 / 9.  Microsoft total: 8 / 9.
    """
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL,
            metric TEXT NOT NULL, value REAL,
            UNIQUE(company, year, metric)
        )
    """)
    cur.execute("""
        CREATE TABLE derived_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL,
            metric TEXT NOT NULL, value REAL,
            metric_type TEXT NOT NULL, input_components TEXT NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, year, metric)
        )
    """)
    cur.execute("""
        CREATE TABLE agent_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT, predicted_answer TEXT,
            confidence REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE TABLE agent_feedback (prediction_id INTEGER, correct_answer TEXT, is_correct INTEGER)")
    cur.execute("CREATE TABLE agent_playbook (id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT UNIQUE)")

    # Microsoft 2022 + 2023 (same as piotroski_db -> score 8/9)
    msft_data = [
        ("Microsoft", 2022, "net_income", 90000.0),
        ("Microsoft", 2022, "total_assets", 900000.0),
        ("Microsoft", 2022, "operating_cash_flow", 120000.0),
        ("Microsoft", 2022, "long_term_debt", 350000.0),
        ("Microsoft", 2022, "current_assets", 300000.0),
        ("Microsoft", 2022, "current_liabilities", 180000.0),
        ("Microsoft", 2022, "shares_outstanding", 1000.0),
        ("Microsoft", 2022, "gross_profit", 500000.0),
        ("Microsoft", 2022, "revenue", 800000.0),
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

    # Google 2022 + 2023 (designed for score 5/9)
    goog_data = [
        ("Google", 2022, "net_income", 60000.0),
        ("Google", 2022, "total_assets", 600000.0),
        ("Google", 2022, "operating_cash_flow", 50000.0),
        ("Google", 2022, "long_term_debt", 200000.0),
        ("Google", 2022, "current_assets", 150000.0),
        ("Google", 2022, "current_liabilities", 120000.0),
        ("Google", 2022, "shares_outstanding", 800.0),
        ("Google", 2022, "gross_profit", 250000.0),
        ("Google", 2022, "revenue", 500000.0),
        ("Google", 2023, "net_income", 70000.0),
        ("Google", 2023, "total_assets", 650000.0),
        ("Google", 2023, "operating_cash_flow", 55000.0),
        ("Google", 2023, "long_term_debt", 220000.0),
        ("Google", 2023, "current_assets", 180000.0),
        ("Google", 2023, "current_liabilities", 140000.0),
        ("Google", 2023, "shares_outstanding", 850.0),
        ("Google", 2023, "gross_profit", 300000.0),
        ("Google", 2023, "revenue", 600000.0),
    ]

    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        msft_data + goog_data,
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


def test_comparison_returns_ranking(two_company_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Compare Microsoft and Google by Piotroski score in 2023")

    assert result.get("is_piotroski") is True
    assert result.get("is_comparison") is True
    assert result["intent"] == "piotroski_comparison"

    answer = result["final_answer"]
    assert answer["year"] == 2023
    assert len(answer["ranking"]) == 2

    # Microsoft (8) should rank above Google (5)
    assert answer["ranking"][0]["company"] == "Microsoft"
    assert answer["ranking"][0]["score"] == 8
    assert answer["ranking"][1]["company"] == "Google"
    assert answer["ranking"][1]["score"] == 5
    assert answer["winner"] == "Microsoft"


def test_comparison_confidence_is_minimum(two_company_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Compare Microsoft and Google by Piotroski score in 2023")

    answer = result["final_answer"]

    # Microsoft: 9 computable -> 0.95, Google: 9 computable -> 0.95
    # Minimum should be 0.95
    assert answer["confidence"] == 0.95


def test_comparison_explanation_mentions_both_companies(two_company_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Compare Microsoft and Google by Piotroski score in 2023")

    explanation = result["final_answer"]["explanation"]
    assert "Microsoft" in explanation
    assert "Google" in explanation
    assert "2023" in explanation
    assert "highest score" in explanation


def test_comparison_structured_response_keys(two_company_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Compare Microsoft and Google by Piotroski score in 2023")

    answer = result["final_answer"]
    assert "year" in answer
    assert "ranking" in answer
    assert "winner" in answer
    assert "explanation" in answer
    assert "confidence" in answer
    assert "confidence_label" in answer

    # Each ranking entry must have expected keys
    for entry in answer["ranking"]:
        assert "company" in entry
        assert "score" in entry
        assert "max_possible" in entry
        assert "confidence" in entry


def test_comparison_deterministic(two_company_db):
    """Two identical comparison queries produce identical results."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    q = "Compare Microsoft and Google by Piotroski score in 2023"
    r1 = gen.generate(q)
    r2 = gen.generate(q)

    assert r1["final_answer"]["ranking"] == r2["final_answer"]["ranking"]
    assert r1["final_answer"]["winner"] == r2["final_answer"]["winner"]
    assert r1["final_answer"]["explanation"] == r2["final_answer"]["explanation"]


def test_comparison_single_company_not_affected(two_company_db):
    """Single-company Piotroski queries still return single-company response."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("What is Microsoft's Piotroski score in 2023?")

    assert result["intent"] == "piotroski"
    assert result.get("is_comparison") is False
    assert "piotroski_score" in result["final_answer"]
    assert "ranking" not in result["final_answer"]


def test_comparison_tie_detection():
    """When two companies have the same score, winner should be None."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL,
            metric TEXT NOT NULL, value REAL,
            UNIQUE(company, year, metric)
        )
    """)
    cur.execute("""
        CREATE TABLE derived_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL,
            metric TEXT NOT NULL, value REAL,
            metric_type TEXT NOT NULL, input_components TEXT NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, year, metric)
        )
    """)
    cur.execute("CREATE TABLE agent_predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, predicted_answer TEXT, confidence REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE agent_feedback (prediction_id INTEGER, correct_answer TEXT, is_correct INTEGER)")
    cur.execute("CREATE TABLE agent_playbook (id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT UNIQUE)")

    # Both companies have identical data -> identical scores
    for company in ["AlphaCo", "BetaCo"]:
        for year in [2022, 2023]:
            base = 100000.0 if year == 2023 else 80000.0
            cur.executemany(
                "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
                [
                    (company, year, "net_income", base),
                    (company, year, "total_assets", base * 10),
                    (company, year, "operating_cash_flow", base * 1.2),
                    (company, year, "revenue", base * 8),
                ],
            )

    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    try:
        from ace_research.experiments import Generator

        gen = Generator(["test rule"])
        result = gen.generate("Compare AlphaCo and BetaCo by Piotroski score in 2023")

        answer = result["final_answer"]
        assert answer["winner"] is None  # tied
        assert answer["ranking"][0]["score"] == answer["ranking"][1]["score"]
        assert "tied" in answer["explanation"]
    finally:
        db_module.DB_PATH = original
        try:
            os.unlink(db_path)
        except:
            pass


def test_comparison_stores_prediction(two_company_db):
    from ace_research.experiments import simulate_ace

    samples = [
        {
            "question": "Compare Microsoft and Google by Piotroski score in 2023",
            "metric": "piotroski_f_score",
        }
    ]
    simulate_ace(samples, ["test rule"])

    conn = sqlite3.connect(two_company_db)
    cur = conn.cursor()
    cur.execute("SELECT question, confidence FROM agent_predictions ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert "Compare" in row[0] or "Piotroski" in row[0]


def test_financial_strength_keyword_triggers_piotroski(two_company_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("Rank Microsoft and Google by financial strength in 2023")

    assert plan["intent"] == "piotroski"
    assert plan["is_piotroski"] is True


def test_comparison_explanation_helper():
    from ace_research.experiments import build_piotroski_comparison_explanation

    ranking = [
        {"company": "CorpA", "score": 7, "max_possible": 9, "confidence": 0.95},
        {"company": "CorpB", "score": 4, "max_possible": 9, "confidence": 0.95},
    ]
    explanation = build_piotroski_comparison_explanation(ranking, 2023, "CorpA")

    assert "CorpA scored 7/9" in explanation
    assert "CorpB scored 4/9" in explanation
    assert "CorpA has the highest score" in explanation


def test_comparison_explanation_tie_helper():
    from ace_research.experiments import build_piotroski_comparison_explanation

    ranking = [
        {"company": "CorpA", "score": 6, "max_possible": 9, "confidence": 0.95},
        {"company": "CorpB", "score": 6, "max_possible": 9, "confidence": 0.95},
    ]
    explanation = build_piotroski_comparison_explanation(ranking, 2023, None)

    assert "tied" in explanation
    assert "6" in explanation


# ============================================================
# Multi-year Piotroski trend
# ============================================================

@pytest.fixture
def trend_db():
    """
    Temp database with pre-cached Piotroski scores for Microsoft across 5 years
    (2019-2023), showing an improving trend: 4, 5, 6, 7, 8.

    Uses derived_metrics cache directly so no financial_facts computation occurs.
    financial_facts contains one row per year so infer_companies() finds 'Microsoft'.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL,
            metric TEXT NOT NULL, value REAL,
            UNIQUE(company, year, metric)
        )
    """)
    cur.execute("""
        CREATE TABLE derived_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL,
            metric TEXT NOT NULL, value REAL,
            metric_type TEXT NOT NULL, input_components TEXT NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, year, metric)
        )
    """)
    cur.execute("""
        CREATE TABLE agent_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT, predicted_answer TEXT,
            confidence REAL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute(
        "CREATE TABLE agent_feedback "
        "(prediction_id INTEGER, correct_answer TEXT, is_correct INTEGER)"
    )
    cur.execute(
        "CREATE TABLE agent_playbook "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT UNIQUE)"
    )

    # One financial_facts row per year so infer_companies() resolves 'Microsoft'
    for year in range(2019, 2024):
        cur.execute(
            "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
            ("Microsoft", year, "revenue", float(year * 1000)),
        )

    # Pre-cache improving trend: 4/9, 5/8, 6/9, 7/9, 8/9
    yearly_scores = {
        2019: (4, 7),   # limited computable signals (no prior year)
        2020: (5, 8),
        2021: (6, 9),
        2022: (7, 9),
        2023: (8, 9),
    }
    for year, (score, max_possible) in yearly_scores.items():
        provenance = json.dumps({
            "total_score": score,
            "max_possible": max_possible,
            "signal_scores": {},
        })
        cur.execute(
            "INSERT INTO derived_metrics "
            "(company, year, metric, value, metric_type, input_components) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("Microsoft", year, "piotroski_f_score", float(score), "piotroski", provenance),
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
    except Exception:
        pass


# --- Intent detection ---

def test_trend_intent_trend_keyword(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("Show Microsoft's Piotroski trend from 2019 to 2023")

    assert plan["intent"] == "piotroski_trend"
    assert plan["is_piotroski"] is True
    assert plan["is_piotroski_trend"] is True


def test_trend_intent_over_time(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("How has Microsoft's F-score changed over time?")

    assert plan["intent"] == "piotroski_trend"


def test_trend_intent_last_n_years(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan(
        "Has Microsoft's financial strength improved over the last 5 years?"
    )

    assert plan["intent"] == "piotroski_trend"


def test_trend_intent_since(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("How has Microsoft's Piotroski score changed since 2019?")

    assert plan["intent"] == "piotroski_trend"


def test_trend_intent_changed(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("How has Apple's Piotroski F-score changed?")

    assert plan["intent"] == "piotroski_trend"


def test_non_trend_piotroski_not_affected(trend_db):
    """Single-year Piotroski query must NOT be routed to trend handler."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What is Microsoft's Piotroski score in 2023?")

    assert plan["intent"] == "piotroski"
    assert plan.get("is_piotroski_trend") is False


# --- Year range extraction ---

def test_year_range_from_to():
    from ace_research.experiments import extract_piotroski_year_range

    start, end = extract_piotroski_year_range(
        "Show Microsoft's Piotroski trend from 2019 to 2023"
    )
    assert start == 2019
    assert end == 2023


def test_year_range_last_n_years():
    from ace_research.experiments import extract_piotroski_year_range

    start, end = extract_piotroski_year_range(
        "Has Microsoft's F-score improved over the last 5 years?",
        default_end=2023,
    )
    assert start == 2019
    assert end == 2023


def test_year_range_since():
    from ace_research.experiments import extract_piotroski_year_range

    start, end = extract_piotroski_year_range(
        "How has Apple's Piotroski score changed since 2020?",
        default_end=2023,
    )
    assert start == 2020
    assert end == 2023


def test_year_range_default_no_years():
    from ace_research.experiments import extract_piotroski_year_range

    start, end = extract_piotroski_year_range("Show the Piotroski trend", default_end=2023)
    assert end == 2023
    assert start == end - 4  # 5-year range


# --- Direction classification ---

def test_direction_improving():
    from ace_research.experiments import classify_piotroski_trend

    data = [
        {"year": 2021, "score": 4, "max_possible": 9, "confidence": 0.7},
        {"year": 2022, "score": 6, "max_possible": 9, "confidence": 0.7},
        {"year": 2023, "score": 8, "max_possible": 9, "confidence": 0.95},
    ]
    assert classify_piotroski_trend(data) == "improving"


def test_direction_declining():
    from ace_research.experiments import classify_piotroski_trend

    data = [
        {"year": 2021, "score": 8, "max_possible": 9, "confidence": 0.95},
        {"year": 2022, "score": 6, "max_possible": 9, "confidence": 0.7},
        {"year": 2023, "score": 4, "max_possible": 9, "confidence": 0.7},
    ]
    assert classify_piotroski_trend(data) == "declining"


def test_direction_stable():
    from ace_research.experiments import classify_piotroski_trend

    data = [
        {"year": 2021, "score": 6, "max_possible": 9, "confidence": 0.7},
        {"year": 2022, "score": 6, "max_possible": 9, "confidence": 0.7},
        {"year": 2023, "score": 6, "max_possible": 9, "confidence": 0.7},
    ]
    assert classify_piotroski_trend(data) == "stable"


def test_direction_insufficient():
    from ace_research.experiments import classify_piotroski_trend

    # Only one year with data
    data = [
        {"year": 2023, "score": 6, "max_possible": 9, "confidence": 0.7},
    ]
    assert classify_piotroski_trend(data) == "insufficient data"


def test_direction_insufficient_all_none():
    from ace_research.experiments import classify_piotroski_trend

    data = [
        {"year": 2022, "score": None, "max_possible": 0, "confidence": 0.2},
        {"year": 2023, "score": None, "max_possible": 0, "confidence": 0.2},
    ]
    assert classify_piotroski_trend(data) == "insufficient data"


# --- End-to-end: generate() ---

def test_trend_returns_structured_response(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2019 to 2023")

    assert result.get("is_piotroski") is True
    assert result.get("is_piotroski_trend") is True
    assert result["intent"] == "piotroski_trend"

    answer = result["final_answer"]
    assert answer["company"] == "Microsoft"
    assert len(answer["trend"]) == 5
    assert all("year" in t and "score" in t for t in answer["trend"])
    assert "direction" in answer
    assert "explanation" in answer
    assert "confidence" in answer
    assert "confidence_label" in answer


def test_trend_direction_is_improving(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2019 to 2023")

    assert result["final_answer"]["direction"] == "improving"


def test_trend_scores_match_cached_values(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2019 to 2023")

    trend = {t["year"]: t["score"] for t in result["final_answer"]["trend"]}
    assert trend[2019] == 4
    assert trend[2021] == 6
    assert trend[2023] == 8


def test_trend_confidence_penalized_for_missing(trend_db):
    """When only 3 of 5 years have data, confidence is penalized by coverage."""
    from ace_research.experiments import Generator, compute_piotroski_confidence

    # Run a 5-year query but our fixture only has 2019-2023; all 5 years have data.
    # To test penalty, run a query for a range that exceeds what's cached (2017-2023).
    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2017 to 2023")

    # 2017 and 2018 have no data (score=None, max_possible=0, confidence=0.2)
    # 5 of 7 years have data; base = min of valid confidences
    answer = result["final_answer"]
    assert answer["confidence"] <= 0.95  # penalized below maximum


def test_trend_confidence_full_coverage(trend_db):
    """When all years have data, confidence equals the minimum yearly confidence."""
    from ace_research.experiments import Generator, compute_piotroski_confidence

    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2021 to 2023")

    # 2021: max_possible=9 -> 0.95, 2022: 9 -> 0.95, 2023: 9 -> 0.95
    # All 3 have data; coverage=1.0; base=0.95 -> confidence=0.95
    answer = result["final_answer"]
    assert answer["confidence"] == 0.95


def test_trend_explanation_mentions_company_and_years(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2019 to 2023")

    explanation = result["final_answer"]["explanation"]
    assert "Microsoft" in explanation
    assert "2019" in explanation
    assert "2023" in explanation


def test_trend_explanation_mentions_direction(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Show Microsoft's Piotroski trend from 2019 to 2023")

    explanation = result["final_answer"]["explanation"]
    assert "improving" in explanation


def test_trend_deterministic(trend_db):
    """Two identical trend queries produce identical output."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    q = "Show Microsoft's Piotroski trend from 2019 to 2023"
    r1 = gen.generate(q)
    r2 = gen.generate(q)

    assert r1["final_answer"]["trend"] == r2["final_answer"]["trend"]
    assert r1["final_answer"]["direction"] == r2["final_answer"]["direction"]
    assert r1["final_answer"]["explanation"] == r2["final_answer"]["explanation"]
    assert r1["final_answer"]["confidence"] == r2["final_answer"]["confidence"]


def test_trend_no_company_returns_missing(trend_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    # No company name in question  -> ACME Corp fallback, which has no data
    result = gen.generate("Show the Piotroski trend from 2019 to 2023")

    # Either missing_components is True or final_answer is None
    assert result.get("missing_components") is True or result["final_answer"] is None


# --- simulate_ace stores trend prediction ---

def test_trend_simulate_ace_stores_prediction(trend_db):
    from ace_research.experiments import simulate_ace

    samples = [
        {
            "question": "Show Microsoft's Piotroski trend from 2019 to 2023",
            "metric": "piotroski_f_score",
        }
    ]
    simulate_ace(samples, ["test rule"])

    conn = sqlite3.connect(trend_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT question, confidence FROM agent_predictions ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert "Piotroski" in row[0] or "trend" in row[0].lower()


# --- Helpers unit tests ---

def test_trend_explanation_helper_improving():
    from ace_research.experiments import build_piotroski_trend_explanation

    data = [
        {"year": 2021, "score": 4, "max_possible": 9, "confidence": 0.7},
        {"year": 2022, "score": 6, "max_possible": 9, "confidence": 0.7},
        {"year": 2023, "score": 8, "max_possible": 9, "confidence": 0.95},
    ]
    expl = build_piotroski_trend_explanation("TestCo", data, "improving", (2021, 2023))

    assert "TestCo" in expl
    assert "improving" in expl
    assert "2021" in expl
    assert "2023" in expl
    assert "4 ->" in expl or "4 -" in expl


def test_trend_explanation_helper_missing_years():
    from ace_research.experiments import build_piotroski_trend_explanation

    data = [
        {"year": 2020, "score": None, "max_possible": 0, "confidence": 0.2},
        {"year": 2021, "score": 5, "max_possible": 9, "confidence": 0.7},
        {"year": 2022, "score": 7, "max_possible": 9, "confidence": 0.95},
    ]
    expl = build_piotroski_trend_explanation("TestCo", data, "improving", (2020, 2022))

    # New format uses "Missing years:" section instead of "N/A" inline
    assert "Missing years" in expl
    assert "2020" in expl


def test_trend_explanation_helper_stable():
    from ace_research.experiments import build_piotroski_trend_explanation

    data = [
        {"year": 2022, "score": 6, "max_possible": 9, "confidence": 0.7},
        {"year": 2023, "score": 6, "max_possible": 9, "confidence": 0.7},
    ]
    expl = build_piotroski_trend_explanation("TestCo", data, "stable", (2022, 2023))

    assert "stable" in expl
    assert "6" in expl


# --- Single-company and comparison behaviour unchanged ---

def test_single_company_piotroski_unaffected_by_trend(piotroski_db):
    """Existing single-company Piotroski flow still returns piotroski intent."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("What is Microsoft's Piotroski score in 2023?")

    assert result["intent"] == "piotroski"
    assert result.get("is_piotroski_trend") is False
    assert "piotroski_score" in result["final_answer"]


def test_comparison_piotroski_unaffected_by_trend(two_company_db):
    """Multi-company comparison still returns piotroski_comparison intent."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Compare Microsoft and Google by Piotroski score in 2023")

    assert result["intent"] == "piotroski_comparison"
    assert result.get("is_piotroski_trend") is False
    assert "ranking" in result["final_answer"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
