"""
Tests for Piotroski F-Score computation.

Uses controlled test data to verify each of the 9 signals independently,
plus the aggregator and persistence logic.

All data is injected into a temp DB so tests are deterministic and
independent of actual filing data.
"""

import pytest
import sqlite3
import tempfile
import os
import json


@pytest.fixture
def test_db():
    """
    Create a temp database with financial_facts + derived_metrics,
    populated with two years of clean data for a test company.

    Data designed so that:
      Profitability:
        1. ROA(2023) = 150k / 1M = 0.15 > 0            -> 1
        2. CFO(2023) = 200k > 0                         -> 1
        3. delta ROA = 0.15 - 0.10 = 0.05 > 0           -> 1
        4. accruals = (200k - 150k) / 1M = 0.05 > 0     -> 1

      Leverage/Liquidity:
        5. leverage(2023) = 300k/1M = 0.30
           leverage(2022) = 350k/900k = 0.389 -> delta = -0.089 < 0   -> 1
        6. liquidity(2023) = 400k/200k = 2.0
           liquidity(2022) = 300k/180k = 1.667 -> delta = 0.333 > 0   -> 1
        7. shares(2023)=1000, shares(2022)=1000 -> delta=0 <= 0        -> 1

      Efficiency:
        8. gm(2023) = 600k/1M_rev = 0.60
           gm(2022) = 500k/800k = 0.625 -> delta = -0.025 < 0        -> 0
        9. at(2023) = 1M_rev / 1M_assets = 1.0
           at(2022) = 800k / 900k = 0.889 -> delta = 0.111 > 0       -> 1

    Expected total: 8 / 9
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

    # Year 2022 (prior year)
    data_2022 = [
        ("TestCo", 2022, "net_income", 90000.0),         # ROA = 90k/900k = 0.10
        ("TestCo", 2022, "total_assets", 900000.0),
        ("TestCo", 2022, "operating_cash_flow", 120000.0),
        ("TestCo", 2022, "long_term_debt", 350000.0),     # leverage = 350k/900k
        ("TestCo", 2022, "current_assets", 300000.0),     # liquidity = 300k/180k
        ("TestCo", 2022, "current_liabilities", 180000.0),
        ("TestCo", 2022, "shares_outstanding", 1000.0),
        ("TestCo", 2022, "gross_profit", 500000.0),       # gm = 500k/800k
        ("TestCo", 2022, "revenue", 800000.0),            # at = 800k/900k
    ]

    # Year 2023 (current year)
    data_2023 = [
        ("TestCo", 2023, "net_income", 150000.0),         # ROA = 150k/1M = 0.15
        ("TestCo", 2023, "total_assets", 1000000.0),
        ("TestCo", 2023, "operating_cash_flow", 200000.0),
        ("TestCo", 2023, "long_term_debt", 300000.0),     # leverage = 300k/1M
        ("TestCo", 2023, "current_assets", 400000.0),     # liquidity = 400k/200k
        ("TestCo", 2023, "current_liabilities", 200000.0),
        ("TestCo", 2023, "shares_outstanding", 1000.0),   # no change
        ("TestCo", 2023, "gross_profit", 600000.0),       # gm = 600k/1M
        ("TestCo", 2023, "revenue", 1000000.0),           # at = 1M/1M
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
def weak_db():
    """
    A database with intentionally MISSING data for edge-case testing.
    Only has net_income and total_assets for 2023. Nothing else.
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

    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        [
            ("SparseInc", 2023, "net_income", 50000.0),
            ("SparseInc", 2023, "total_assets", 500000.0),
        ],
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


# ============================================================
# Profitability signals
# ============================================================

def test_roa_signal_positive(test_db):
    from ace_research.piotroski import compute_roa_signal

    result = compute_roa_signal("TestCo", 2023)

    assert result["score"] == 1
    assert result["signal"] == "roa_positive"
    assert abs(result["value"] - 0.15) < 1e-6
    assert result["inputs"]["net_income"] == 150000.0
    assert result["inputs"]["total_assets"] == 1000000.0


def test_cfo_signal_positive(test_db):
    from ace_research.piotroski import compute_cfo_signal

    result = compute_cfo_signal("TestCo", 2023)

    assert result["score"] == 1
    assert result["value"] == 200000.0


def test_delta_roa_signal_positive(test_db):
    from ace_research.piotroski import compute_delta_roa_signal

    result = compute_delta_roa_signal("TestCo", 2023)

    # ROA 2023 = 0.15, ROA 2022 = 0.10, delta = 0.05
    assert result["score"] == 1
    assert abs(result["value"] - 0.05) < 1e-6
    assert abs(result["inputs"]["roa_current"] - 0.15) < 1e-6
    assert abs(result["inputs"]["roa_prior"] - 0.10) < 1e-6


def test_accruals_signal_positive(test_db):
    from ace_research.piotroski import compute_accruals_signal

    result = compute_accruals_signal("TestCo", 2023)

    # accruals = (200k - 150k) / 1M = 0.05 > 0 -> score 1
    assert result["score"] == 1
    assert abs(result["value"] - 0.05) < 1e-6


# ============================================================
# Leverage / Liquidity / Source of Funds signals
# ============================================================

def test_delta_leverage_signal_negative(test_db):
    from ace_research.piotroski import compute_delta_leverage_signal

    result = compute_delta_leverage_signal("TestCo", 2023)

    # leverage 2023 = 300k/1M = 0.30
    # leverage 2022 = 350k/900k = 0.38889
    # delta = -0.08889 < 0 -> score 1
    assert result["score"] == 1
    assert result["value"] < 0


def test_delta_liquidity_signal_positive(test_db):
    from ace_research.piotroski import compute_delta_liquidity_signal

    result = compute_delta_liquidity_signal("TestCo", 2023)

    # liquidity 2023 = 400k/200k = 2.0
    # liquidity 2022 = 300k/180k = 1.6667
    # delta = 0.3333 > 0 -> score 1
    assert result["score"] == 1
    assert result["value"] > 0


def test_no_equity_issuance_signal_no_change(test_db):
    from ace_research.piotroski import compute_no_equity_issuance_signal

    result = compute_no_equity_issuance_signal("TestCo", 2023)

    # shares 2023 = 1000, shares 2022 = 1000, delta = 0 <= 0 -> score 1
    assert result["score"] == 1
    assert result["value"] == 0.0


# ============================================================
# Operating Efficiency signals
# ============================================================

def test_delta_gross_margin_signal_negative(test_db):
    from ace_research.piotroski import compute_delta_gross_margin_signal

    result = compute_delta_gross_margin_signal("TestCo", 2023)

    # gm 2023 = 600k/1M = 0.60
    # gm 2022 = 500k/800k = 0.625
    # delta = -0.025 < 0 -> score 0
    assert result["score"] == 0
    assert result["value"] < 0


def test_delta_asset_turnover_signal_positive(test_db):
    from ace_research.piotroski import compute_delta_asset_turnover_signal

    result = compute_delta_asset_turnover_signal("TestCo", 2023)

    # at 2023 = 1M/1M = 1.0
    # at 2022 = 800k/900k = 0.8889
    # delta = 0.1111 > 0 -> score 1
    assert result["score"] == 1
    assert result["value"] > 0


# ============================================================
# Aggregator
# ============================================================

def test_piotroski_total_score(test_db):
    from ace_research.piotroski import compute_piotroski_score

    result = compute_piotroski_score("TestCo", 2023)

    assert result["company"] == "TestCo"
    assert result["year"] == 2023
    assert result["total_score"] == 8
    assert result["max_possible"] == 9

    # Check all 9 signals present
    assert len(result["signals"]) == 9


def test_piotroski_all_signals_have_required_keys(test_db):
    from ace_research.piotroski import compute_piotroski_score

    result = compute_piotroski_score("TestCo", 2023)

    for name, sig in result["signals"].items():
        assert "signal" in sig, f"Missing 'signal' key in {name}"
        assert "score" in sig, f"Missing 'score' key in {name}"
        assert "value" in sig, f"Missing 'value' key in {name}"
        assert "inputs" in sig, f"Missing 'inputs' key in {name}"


def test_piotroski_scores_are_binary_or_none(test_db):
    from ace_research.piotroski import compute_piotroski_score

    result = compute_piotroski_score("TestCo", 2023)

    for name, sig in result["signals"].items():
        assert sig["score"] in (0, 1, None), \
            f"Signal {name} has invalid score: {sig['score']}"


# ============================================================
# Missing data handling
# ============================================================

def test_missing_prior_year_gives_none(weak_db):
    from ace_research.piotroski import compute_delta_roa_signal

    result = compute_delta_roa_signal("SparseInc", 2023)

    # No 2022 data, so delta ROA should be None
    assert result["score"] is None
    assert result["value"] is None


def test_missing_cfo_gives_none(weak_db):
    from ace_research.piotroski import compute_cfo_signal

    result = compute_cfo_signal("SparseInc", 2023)

    # No operating_cash_flow -> None
    assert result["score"] is None
    assert result["value"] is None


def test_roa_computable_with_minimal_data(weak_db):
    from ace_research.piotroski import compute_roa_signal

    result = compute_roa_signal("SparseInc", 2023)

    # net_income and total_assets exist, so ROA is computable
    assert result["score"] == 1
    assert abs(result["value"] - 0.10) < 1e-6


def test_sparse_piotroski_score_partial(weak_db):
    from ace_research.piotroski import compute_piotroski_score

    result = compute_piotroski_score("SparseInc", 2023)

    # Only ROA is computable (net_income + total_assets present)
    assert result["total_score"] == 1
    assert result["max_possible"] == 1

    # All other signals should be None
    none_count = sum(
        1 for sig in result["signals"].values() if sig["score"] is None
    )
    assert none_count == 8


def test_nonexistent_company_all_none(weak_db):
    from ace_research.piotroski import compute_piotroski_score

    result = compute_piotroski_score("NoSuchCorp", 2023)

    assert result["total_score"] is None
    assert result["max_possible"] == 0

    for sig in result["signals"].values():
        assert sig["score"] is None


# ============================================================
# Persistence
# ============================================================

def test_persist_stores_all_signals(test_db):
    from ace_research.piotroski import persist_piotroski_score

    result = persist_piotroski_score("TestCo", 2023)

    # Verify rows in derived_metrics
    conn = sqlite3.connect(test_db)
    cur = conn.cursor()

    cur.execute(
        "SELECT metric, value FROM derived_metrics WHERE company='TestCo' AND year=2023 ORDER BY metric"
    )
    rows = cur.fetchall()
    conn.close()

    metrics_stored = {row[0] for row in rows}

    # 9 individual signals + 1 total
    assert len(rows) == 10
    assert "piotroski_f_score" in metrics_stored
    assert "piotroski_roa_positive" in metrics_stored
    assert "piotroski_cfo_positive" in metrics_stored


def test_persist_f_score_value(test_db):
    from ace_research.piotroski import persist_piotroski_score

    persist_piotroski_score("TestCo", 2023)

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()

    cur.execute("""
        SELECT value, input_components
        FROM derived_metrics
        WHERE company='TestCo' AND year=2023 AND metric='piotroski_f_score'
    """)
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == 8  # total score

    provenance = json.loads(row[1])
    assert provenance["total_score"] == 8
    assert provenance["max_possible"] == 9


def test_persist_provenance_includes_inputs(test_db):
    from ace_research.piotroski import persist_piotroski_score

    persist_piotroski_score("TestCo", 2023)

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()

    cur.execute("""
        SELECT input_components
        FROM derived_metrics
        WHERE company='TestCo' AND year=2023 AND metric='piotroski_roa_positive'
    """)
    row = cur.fetchone()
    conn.close()

    provenance = json.loads(row[0])
    assert provenance["signal"] == "roa_positive"
    assert "net_income" in provenance["inputs"]
    assert "total_assets" in provenance["inputs"]
    assert provenance["inputs"]["net_income"] == 150000.0


def test_persist_is_idempotent(test_db):
    from ace_research.piotroski import persist_piotroski_score

    # Run twice
    persist_piotroski_score("TestCo", 2023)
    persist_piotroski_score("TestCo", 2023)

    conn = sqlite3.connect(test_db)
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM derived_metrics WHERE company='TestCo' AND year=2023"
    )
    count = cur.fetchone()[0]
    conn.close()

    # Should still be 10 rows (INSERT OR REPLACE), not 20
    assert count == 10


# ============================================================
# Gross margin fallback (cost_of_revenue)
# ============================================================

def test_gross_margin_falls_back_to_cost_of_revenue():
    """
    When gross_profit is unavailable, gross margin should be
    computed as (revenue - cost_of_revenue) / revenue.
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

    # No gross_profit, but has cost_of_revenue
    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        [
            ("FallbackCo", 2022, "revenue", 1000000.0),
            ("FallbackCo", 2022, "cost_of_revenue", 600000.0),  # gm = 0.40
            ("FallbackCo", 2023, "revenue", 1200000.0),
            ("FallbackCo", 2023, "cost_of_revenue", 660000.0),  # gm = 0.45
        ],
    )

    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    try:
        from ace_research.piotroski import compute_delta_gross_margin_signal

        result = compute_delta_gross_margin_signal("FallbackCo", 2023)

        # gm 2023 = (1.2M - 660k) / 1.2M = 0.45
        # gm 2022 = (1M - 600k) / 1M = 0.40
        # delta = 0.05 > 0 -> score 1
        assert result["score"] == 1
        assert abs(result["value"] - 0.05) < 1e-6
    finally:
        db_module.DB_PATH = original
        try:
            os.unlink(db_path)
        except:
            pass


# ============================================================
# Negative / zero edge cases
# ============================================================

def test_roa_negative_gives_zero_score():
    """ROA < 0 should give score 0, not None."""
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
            company TEXT NOT NULL, year INTEGER NOT NULL, metric TEXT NOT NULL,
            value REAL, metric_type TEXT NOT NULL, input_components TEXT NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, year, metric)
        )
    """)

    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        [
            ("LossCo", 2023, "net_income", -50000.0),
            ("LossCo", 2023, "total_assets", 500000.0),
        ],
    )
    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    try:
        from ace_research.piotroski import compute_roa_signal

        result = compute_roa_signal("LossCo", 2023)

        assert result["score"] == 0
        assert result["value"] < 0
    finally:
        db_module.DB_PATH = original
        try:
            os.unlink(db_path)
        except:
            pass


def test_equity_issuance_gives_zero_score():
    """Increased shares outstanding should give score 0."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL, metric TEXT NOT NULL,
            value REAL, UNIQUE(company, year, metric)
        )
    """)
    cur.execute("""
        CREATE TABLE derived_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL, year INTEGER NOT NULL, metric TEXT NOT NULL,
            value REAL, metric_type TEXT NOT NULL, input_components TEXT NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, year, metric)
        )
    """)

    cur.executemany(
        "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
        [
            ("DiluteCo", 2022, "shares_outstanding", 1000.0),
            ("DiluteCo", 2023, "shares_outstanding", 1200.0),  # increased
        ],
    )
    conn.commit()
    conn.close()

    import ace_research.db as db_module
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path

    try:
        from ace_research.piotroski import compute_no_equity_issuance_signal

        result = compute_no_equity_issuance_signal("DiluteCo", 2023)

        assert result["score"] == 0
        assert result["value"] == 200.0
    finally:
        db_module.DB_PATH = original
        try:
            os.unlink(db_path)
        except:
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
