"""
Tests for financial risk flag detection.

Verifies:
1. Intent detection for risk/warning keywords
2. build_risk_flags() - all 6 rules fire on adversarial data
3. build_risk_flags() - correct subset fires on known data
4. build_risk_flags() - no flags on healthy data
5. handle_risk_flags() structured response shape
6. Confidence levels relative to data availability
7. simulate_ace stores risk predictions
8. Piotroski / comparison / trend behavior unchanged
"""

import pytest
import sqlite3
import tempfile
import os
import json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_tables(cur):
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


@pytest.fixture
def risk_db():
    """
    Temp database designed to trigger all 6 risk flags for 'RiskCo' in 2023.

    Financial facts:
      2022: net_income=100k, total_assets=1M (ROA=0.10)
            gross_profit=600k, revenue=1M    (GM=0.60)
            long_term_debt=200k              (Lev=0.20)
            current_assets=400k, cl=200k    (Liq=2.0)
            operating_cash_flow=120k

      2023: net_income=80k, total_assets=1M (ROA=0.08 < 0.10 → Rule 2)
            gross_profit=550k, revenue=1M   (GM=0.55 < 0.60 → Rule 3)
            long_term_debt=300k             (Lev=0.30 > 0.20 → Rule 4)
            current_assets=350k, cl=200k   (Liq=1.75 < 2.0  → Rule 5)
            operating_cash_flow=50k        (CFO < NI         → Rule 6)

    Piotroski pre-cached at score=2 → Rule 1 fires.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    rows_2022 = [
        ("RiskCo", 2022, "net_income", 100000.0),
        ("RiskCo", 2022, "total_assets", 1000000.0),
        ("RiskCo", 2022, "gross_profit", 600000.0),
        ("RiskCo", 2022, "revenue", 1000000.0),
        ("RiskCo", 2022, "long_term_debt", 200000.0),
        ("RiskCo", 2022, "current_assets", 400000.0),
        ("RiskCo", 2022, "current_liabilities", 200000.0),
        ("RiskCo", 2022, "operating_cash_flow", 120000.0),
        ("RiskCo", 2022, "shares_outstanding", 1000.0),
    ]
    rows_2023 = [
        ("RiskCo", 2023, "net_income", 80000.0),
        ("RiskCo", 2023, "total_assets", 1000000.0),
        ("RiskCo", 2023, "gross_profit", 550000.0),
        ("RiskCo", 2023, "revenue", 1000000.0),
        ("RiskCo", 2023, "long_term_debt", 300000.0),
        ("RiskCo", 2023, "current_assets", 350000.0),
        ("RiskCo", 2023, "current_liabilities", 200000.0),
        ("RiskCo", 2023, "operating_cash_flow", 50000.0),
        ("RiskCo", 2023, "shares_outstanding", 1000.0),
    ]
    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        rows_2022 + rows_2023,
    )

    # Pre-cache Piotroski score = 2 to trigger Rule 1
    cur.execute(
        "INSERT INTO derived_metrics "
        "(company, year, metric, value, metric_type, input_components) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "RiskCo", 2023, "piotroski_f_score", 2.0, "piotroski",
            json.dumps({"total_score": 2, "max_possible": 9, "signal_scores": {}}),
        ),
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


@pytest.fixture
def healthy_db():
    """
    Temp database with healthy financials for 'HealthCo' — no risk flags.

    2022 → 2023: ROA improved, GM improved, leverage down, liquidity up,
    CFO > Net Income, Piotroski pre-cached at 8.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    rows = [
        ("HealthCo", 2022, "net_income", 80000.0),
        ("HealthCo", 2022, "total_assets", 1000000.0),
        ("HealthCo", 2022, "gross_profit", 500000.0),
        ("HealthCo", 2022, "revenue", 900000.0),
        ("HealthCo", 2022, "long_term_debt", 300000.0),
        ("HealthCo", 2022, "current_assets", 300000.0),
        ("HealthCo", 2022, "current_liabilities", 200000.0),
        ("HealthCo", 2022, "operating_cash_flow", 100000.0),
        ("HealthCo", 2022, "shares_outstanding", 1000.0),
        # 2023: every metric better
        ("HealthCo", 2023, "net_income", 120000.0),        # ROA: 0.12 > 0.08 ✓
        ("HealthCo", 2023, "total_assets", 1000000.0),
        ("HealthCo", 2023, "gross_profit", 600000.0),      # GM: 0.60 > 0.556 ✓
        ("HealthCo", 2023, "revenue", 1000000.0),
        ("HealthCo", 2023, "long_term_debt", 250000.0),    # Lev: 0.25 < 0.30 ✓
        ("HealthCo", 2023, "current_assets", 400000.0),    # Liq: 2.0 > 1.5 ✓
        ("HealthCo", 2023, "current_liabilities", 200000.0),
        ("HealthCo", 2023, "operating_cash_flow", 150000.0),  # CFO > NI ✓
        ("HealthCo", 2023, "shares_outstanding", 1000.0),
    ]
    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        rows,
    )

    # Pre-cache Piotroski score = 8 → no flag
    cur.execute(
        "INSERT INTO derived_metrics "
        "(company, year, metric, value, metric_type, input_components) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "HealthCo", 2023, "piotroski_f_score", 8.0, "piotroski",
            json.dumps({"total_score": 8, "max_possible": 9, "signal_scores": {}}),
        ),
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


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def test_risk_intent_risk_keyword(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("Are there any financial risks for RiskCo in 2023?")

    assert plan["intent"] == "risk_flags"
    assert plan["is_risk_flags"] is True
    assert plan.get("is_piotroski") is False


def test_risk_intent_warning(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What warning signs does RiskCo show in 2023?")

    assert plan["intent"] == "risk_flags"


def test_risk_intent_red_flag(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("Is RiskCo showing red flags in 2023?")

    assert plan["intent"] == "risk_flags"


def test_risk_intent_not_triggered_by_piotroski_question(risk_db):
    """A Piotroski question must never route to risk_flags even if it contains 'weakness'."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What is RiskCo's Piotroski score in 2023?")

    assert plan["intent"] == "piotroski"
    assert plan["is_risk_flags"] is False


def test_non_risk_intent_unchanged(risk_db):
    """A plain metric question with no risk/warning keywords must not trigger risk_flags."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    # Company name "RiskCo" would embed the keyword; test with a neutral phrasing
    plan = gen.build_reasoning_plan("What is total assets in 2023?")

    assert plan["intent"] != "risk_flags"
    assert plan["is_risk_flags"] is False


# ---------------------------------------------------------------------------
# build_risk_flags() — all 6 rules
# ---------------------------------------------------------------------------

def test_build_risk_flags_all_six_triggered(risk_db):
    from ace_research.experiments import build_risk_flags

    result = build_risk_flags("RiskCo", 2023)

    assert result["company"] == "RiskCo"
    assert result["year"] == 2023
    assert result["evaluated_rules"] == 6

    flags = result["risk_flags"]
    assert "Weak financial strength" in flags        # Rule 1: score=2 <= 3
    assert "Profitability deteriorating" in flags    # Rule 2: ROA 0.08 < 0.10
    assert "Margin compression" in flags             # Rule 3: GM 0.55 < 0.60
    assert "Rising financial leverage" in flags      # Rule 4: Lev 0.30 > 0.20
    assert "Liquidity weakening" in flags            # Rule 5: Liq 1.75 < 2.0
    assert "Low earnings quality" in flags           # Rule 6: CFO < NI


def test_build_risk_flags_count(risk_db):
    from ace_research.experiments import build_risk_flags

    result = build_risk_flags("RiskCo", 2023)
    assert len(result["risk_flags"]) == 6


def test_build_risk_flags_no_flags_healthy(healthy_db):
    """Healthy company with improving metrics has zero flags."""
    from ace_research.experiments import build_risk_flags

    result = build_risk_flags("HealthCo", 2023)

    assert result["risk_flags"] == []
    assert result["evaluated_rules"] == 6


def test_build_risk_flags_confidence_full_data(risk_db):
    """6 evaluated rules → confidence = 0.9."""
    from ace_research.experiments import build_risk_flags

    result = build_risk_flags("RiskCo", 2023)

    assert result["evaluated_rules"] == 6
    assert result["confidence"] == 0.9


def test_build_risk_flags_confidence_partial_data():
    """Partial data (1 rule evaluable) → confidence = 0.4."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    # Only CFO and net_income → only Rule 6 evaluable
    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        [
            ("SparseCo", 2023, "operating_cash_flow", 50000.0),
            ("SparseCo", 2023, "net_income", 80000.0),
        ],
    )
    # Pre-cache piotroski with score=None (no data)
    cur.execute(
        "INSERT INTO derived_metrics "
        "(company, year, metric, value, metric_type, input_components) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "SparseCo", 2023, "piotroski_f_score", None, "piotroski",
            json.dumps({"total_score": None, "max_possible": 0, "signal_scores": {}}),
        ),
    )
    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    try:
        from ace_research.experiments import build_risk_flags

        result = build_risk_flags("SparseCo", 2023)
        # Rule 1: score=None → not evaluated
        # Rules 2-5: no prior year data → not evaluated
        # Rule 6: CFO=50k < NI=80k → evaluated + flag
        assert result["evaluated_rules"] == 1
        assert result["confidence"] == 0.4
    finally:
        db_module.DB_PATH = original
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_build_risk_flags_no_data_confidence_floor():
    """Zero evaluable rules → confidence floor = 0.2."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)
    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    try:
        from ace_research.experiments import build_risk_flags

        result = build_risk_flags("GhostCo", 2023)
        assert result["evaluated_rules"] == 0
        assert result["confidence"] == 0.2
        assert result["risk_flags"] == []
    finally:
        db_module.DB_PATH = original
        try:
            os.unlink(db_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# build_risk_explanation()
# ---------------------------------------------------------------------------

def test_risk_explanation_with_flags(risk_db):
    from ace_research.experiments import build_risk_flags, build_risk_explanation

    result = build_risk_flags("RiskCo", 2023)
    expl = build_risk_explanation(result)

    assert "RiskCo" in expl
    assert "2023" in expl
    assert "6" in expl          # 6 flags detected
    assert "6/6" in expl        # 6 rules evaluated


def test_risk_explanation_no_flags(healthy_db):
    from ace_research.experiments import build_risk_flags, build_risk_explanation

    result = build_risk_flags("HealthCo", 2023)
    expl = build_risk_explanation(result)

    assert "No risk flags" in expl
    assert "HealthCo" in expl


def test_risk_explanation_no_data():
    from ace_research.experiments import build_risk_explanation

    result = {"company": "GhostCo", "year": 2023, "risk_flags": [], "evaluated_rules": 0}
    expl = build_risk_explanation(result)

    assert "Insufficient data" in expl
    assert "GhostCo" in expl


# ---------------------------------------------------------------------------
# Generator.generate() end-to-end
# ---------------------------------------------------------------------------

def test_generate_risk_flags_returns_structured_response(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Are there any financial risks for RiskCo in 2023?")

    assert result["intent"] == "risk_flags"
    assert result.get("is_risk_flags") is True
    assert result.get("is_piotroski") is False

    answer = result["final_answer"]
    assert answer["company"] == "RiskCo"
    assert answer["year"] == 2023
    assert "risk_flags" in answer
    assert "explanation" in answer
    assert "confidence" in answer
    assert "confidence_label" in answer


def test_generate_risk_flags_all_six_detected(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Are there any financial risks for RiskCo in 2023?")

    assert len(result["final_answer"]["risk_flags"]) == 6


def test_generate_risk_flags_no_flags_healthy(healthy_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Are there any financial risks for HealthCo in 2023?")

    assert result["intent"] == "risk_flags"
    assert result["final_answer"]["risk_flags"] == []


def test_generate_risk_flags_deterministic(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    q = "Are there any financial risks for RiskCo in 2023?"
    r1 = gen.generate(q)
    r2 = gen.generate(q)

    assert r1["final_answer"]["risk_flags"] == r2["final_answer"]["risk_flags"]
    assert r1["final_answer"]["explanation"] == r2["final_answer"]["explanation"]
    assert r1["final_answer"]["confidence"] == r2["final_answer"]["confidence"]


def test_generate_risk_flags_no_company(risk_db):
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Are there any financial risks?")

    # ACME Corp fallback with no data → missing_components True
    assert result.get("missing_components") is True or result["final_answer"] is None


def test_generate_risk_flags_confidence_label_high(risk_db):
    """6 evaluated rules, confidence=0.9 → label='high'."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    result = gen.generate("Are there any financial risks for RiskCo in 2023?")

    answer = result["final_answer"]
    assert answer["confidence"] == 0.9
    assert answer["confidence_label"] == "high"


# ---------------------------------------------------------------------------
# simulate_ace integration
# ---------------------------------------------------------------------------

def test_simulate_ace_stores_risk_prediction(risk_db):
    from ace_research.experiments import simulate_ace

    samples = [
        {
            "question": "Are there any financial risks for RiskCo in 2023?",
            "metric": "risk_flags",
        }
    ]
    simulate_ace(samples, ["test rule"])

    conn = sqlite3.connect(risk_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT question, confidence FROM agent_predictions ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert "risk" in row[0].lower() or "RiskCo" in row[0]
    assert row[1] == 0.9  # 6 rules evaluated → confidence 0.9


# ---------------------------------------------------------------------------
# Piotroski / comparison / trend — unchanged by risk flags addition
# ---------------------------------------------------------------------------

def test_piotroski_intent_unaffected_by_risk_keywords(risk_db):
    """A Piotroski question is never mistaken for risk_flags."""
    from ace_research.experiments import Generator

    gen = Generator(["test rule"])
    plan = gen.build_reasoning_plan("What is RiskCo's Piotroski F-score in 2023?")

    assert plan["intent"] == "piotroski"
    assert plan["is_risk_flags"] is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
