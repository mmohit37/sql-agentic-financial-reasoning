"""
tests/test_backtest.py

Unit tests for ace_research/backtest.py.

Coverage:
  - Layer 2: compute_forward_performance()
  - Layer 3: aggregate_by_score_bucket()
  - Entrypoint: run_piotroski_backtest()
"""

import json
import os
import sqlite3
import tempfile

import pytest


# =============================================================================
# Shared fixture helpers
# =============================================================================

# Financial facts by year for HighCo (scores 7-9 bucket)
HIGHCO_FACTS = {
    2021: {"revenue": 1000.0, "net_income": 100.0, "total_assets": 2000.0},
    2022: {"revenue": 1100.0, "net_income": 110.0, "total_assets": 2100.0},
    2023: {"revenue": 1210.0, "net_income": 120.0, "total_assets": 2200.0},
}

# Financial facts by year for LowCo (scores 0-3 bucket)
LOWCO_FACTS = {
    2021: {"revenue": 500.0,  "net_income": 10.0, "total_assets": 1000.0},
    2022: {"revenue": 480.0,  "net_income":  8.0, "total_assets": 1050.0},
    2023: {"revenue": 460.0,  "net_income":  7.0, "total_assets": 1100.0},
}

# Pre-cached Piotroski scores (score, max_possible)
HIGHCO_SCORES = {2021: (7, 9), 2022: (7, 9), 2023: (8, 9)}
LOWCO_SCORES  = {2021: (2, 7), 2022: (3, 8), 2023: (2, 7)}


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


def _insert_facts(cur, company, facts_by_year):
    for year, metrics in facts_by_year.items():
        for metric, value in metrics.items():
            cur.execute(
                "INSERT INTO financial_facts (company, year, metric, value) "
                "VALUES (?, ?, ?, ?)",
                (company, year, metric, value),
            )


def _insert_scores(cur, company, scores_by_year):
    for year, (score, max_possible) in scores_by_year.items():
        provenance = json.dumps({
            "total_score": score,
            "max_possible": max_possible,
            "signal_scores": {},
        })
        cur.execute(
            "INSERT INTO derived_metrics "
            "(company, year, metric, value, metric_type, input_components) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (company, year, "piotroski_f_score", float(score), "piotroski", provenance),
        )


@pytest.fixture
def backtest_db():
    """
    Temp SQLite DB with:
    - HighCo (scores 7/7/8, years 2021-2023, growing revenue and net_income)
    - LowCo  (scores 2/3/2, years 2021-2023, declining revenue and net_income)
    - Pre-cached Piotroski scores so no Piotroski computation occurs.

    Observations at run_piotroski_backtest():
        HighCo 2021 (score=7) -> high bucket
        HighCo 2022 (score=7) -> high bucket
        LowCo  2021 (score=2) -> low bucket
        LowCo  2022 (score=3) -> low bucket
    2023 is last year for both companies -> no forward year -> excluded.
    Total = 4 records.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)
    _insert_facts(cur, "HighCo", HIGHCO_FACTS)
    _insert_scores(cur, "HighCo", HIGHCO_SCORES)
    _insert_facts(cur, "LowCo", LOWCO_FACTS)
    _insert_scores(cur, "LowCo", LOWCO_SCORES)
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


# =============================================================================
# Layer 2: compute_forward_performance
# =============================================================================

class TestComputeForwardPerformance:

    def test_revenue_growth_computed_correctly(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("HighCo", 2021)
        assert result is not None
        # (1100 - 1000) / 1000 = 0.1
        assert abs(result["revenue_growth"] - 0.1) < 1e-6

    def test_net_income_growth_computed_correctly(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("HighCo", 2021)
        assert result is not None
        # (110 - 100) / 100 = 0.1
        assert abs(result["net_income_growth"] - 0.1) < 1e-6

    def test_roa_change_computed_correctly(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("HighCo", 2021)
        assert result is not None
        roa_t  = 100.0 / 2000.0   # 0.05
        roa_t1 = 110.0 / 2100.0   # ~0.05238
        expected_change = roa_t1 - roa_t
        assert abs(result["roa_change"] - expected_change) < 1e-8

    def test_returns_none_when_no_forward_year(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        # 2023 is the last year — 2024 has no data
        result = compute_forward_performance("HighCo", 2023)
        assert result is None

    def test_returns_none_for_unknown_company(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("NonexistentCorp", 2021)
        assert result is None

    def test_declining_revenue_for_lowco(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("LowCo", 2021)
        assert result is not None
        assert result["revenue_growth"] < 0    # 480 < 500

    def test_declining_net_income_for_lowco(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("LowCo", 2021)
        assert result is not None
        assert result["net_income_growth"] < 0  # 8 < 10

    def test_declining_roa_for_lowco(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("LowCo", 2021)
        assert result is not None
        assert result["roa_change"] < 0         # roa degrades

    def test_unknown_mode_raises(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        with pytest.raises(NotImplementedError):
            compute_forward_performance("HighCo", 2021, mode="market")

    def test_explicit_financial_mode_matches_default(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        r_default  = compute_forward_performance("HighCo", 2021)
        r_explicit = compute_forward_performance("HighCo", 2021, mode="financial")
        assert r_default == r_explicit

    def test_result_keys_present(self, backtest_db):
        from ace_research.backtest import compute_forward_performance
        result = compute_forward_performance("HighCo", 2021)
        assert result is not None
        assert set(result.keys()) == {"revenue_growth", "net_income_growth", "roa_change"}


# =============================================================================
# Layer 3: aggregate_by_score_bucket
# =============================================================================

class TestAggregateByScoreBucket:

    @staticmethod
    def _rec(score, rev=None, ni=None, roa=None):
        return {
            "score": score,
            "performance": {
                "revenue_growth": rev,
                "net_income_growth": ni,
                "roa_change": roa,
            },
        }

    def test_empty_input_returns_zero_observations(self):
        from ace_research.backtest import aggregate_by_score_bucket
        result = aggregate_by_score_bucket([])
        assert result["total_observations"] == 0
        assert result["high"]["sample_size"] == 0
        assert result["medium"]["sample_size"] == 0
        assert result["low"]["sample_size"] == 0
        assert result["confidence"] == 0.3

    def test_scores_7_8_9_go_to_high_bucket(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(s, 0.1, 0.1, 0.01) for s in (7, 8, 9)]
        result = aggregate_by_score_bucket(records)
        assert result["high"]["sample_size"] == 3
        assert result["medium"]["sample_size"] == 0
        assert result["low"]["sample_size"] == 0

    def test_scores_4_5_6_go_to_medium_bucket(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(s, 0.05, 0.05, 0.005) for s in (4, 5, 6)]
        result = aggregate_by_score_bucket(records)
        assert result["medium"]["sample_size"] == 3
        assert result["high"]["sample_size"] == 0
        assert result["low"]["sample_size"] == 0

    def test_scores_0_1_2_3_go_to_low_bucket(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(s, -0.05, -0.05, -0.005) for s in (0, 1, 2, 3)]
        result = aggregate_by_score_bucket(records)
        assert result["low"]["sample_size"] == 4

    def test_avg_revenue_growth_correct(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [
            self._rec(7, 0.1, 0.1, 0.01),
            self._rec(8, 0.2, 0.2, 0.02),
            self._rec(9, 0.3, 0.3, 0.03),
        ]
        result = aggregate_by_score_bucket(records)
        assert abs(result["high"]["avg_revenue_growth"] - 0.2) < 1e-4

    def test_avg_excludes_none_values(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [
            self._rec(7, 0.1, None, 0.01),
            self._rec(8, 0.3, None, 0.03),
        ]
        result = aggregate_by_score_bucket(records)
        # revenue_growth: avg of 0.1 and 0.3 = 0.2
        assert abs(result["high"]["avg_revenue_growth"] - 0.2) < 1e-4
        # net_income_growth: all None -> None
        assert result["high"]["avg_net_income_growth"] is None

    def test_empty_bucket_avgs_are_none(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(8, 0.1, 0.1, 0.01)]  # only high bucket populated
        result = aggregate_by_score_bucket(records)
        assert result["medium"]["avg_revenue_growth"] is None
        assert result["low"]["avg_revenue_growth"] is None

    def test_confidence_below_3_is_0_3(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(8, 0.1, 0.1, 0.01), self._rec(7, 0.2, 0.2, 0.02)]
        result = aggregate_by_score_bucket(records)
        assert result["confidence"] == 0.3
        assert result["confidence_label"] == "low"

    def test_confidence_3_to_7_is_0_5(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(8, 0.1, 0.1, 0.01) for _ in range(5)]
        result = aggregate_by_score_bucket(records)
        assert result["confidence"] == 0.5
        assert result["confidence_label"] == "medium"

    def test_confidence_8_to_14_is_0_7(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(7, 0.1, 0.1, 0.01) for _ in range(10)]
        result = aggregate_by_score_bucket(records)
        assert result["confidence"] == 0.7
        assert result["confidence_label"] == "medium"

    def test_confidence_15_plus_is_0_9(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(7, 0.1, 0.1, 0.01) for _ in range(15)]
        result = aggregate_by_score_bucket(records)
        assert result["confidence"] == 0.9
        assert result["confidence_label"] == "high"

    def test_total_observations(self):
        from ace_research.backtest import aggregate_by_score_bucket
        records = [self._rec(8, 0.1), self._rec(5, 0.05), self._rec(2, -0.05)]
        result = aggregate_by_score_bucket(records)
        assert result["total_observations"] == 3

    def test_required_keys_present(self):
        from ace_research.backtest import aggregate_by_score_bucket
        result = aggregate_by_score_bucket([])
        for bucket in ("high", "medium", "low"):
            assert "avg_revenue_growth" in result[bucket]
            assert "avg_net_income_growth" in result[bucket]
            assert "avg_roa_change" in result[bucket]
            assert "sample_size" in result[bucket]
        assert "total_observations" in result
        assert "confidence" in result
        assert "confidence_label" in result


# =============================================================================
# Entrypoint: run_piotroski_backtest
# =============================================================================

class TestRunPiotroskiBacktest:

    def test_returns_required_top_level_keys(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["HighCo", "LowCo"])
        for key in ("high", "medium", "low", "total_observations",
                    "confidence", "confidence_label"):
            assert key in result

    def test_high_bucket_populated_from_highco(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["HighCo"])
        # HighCo 2021 (score=7) and 2022 (score=7) both have forward years
        assert result["high"]["sample_size"] == 2

    def test_low_bucket_populated_from_lowco(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["LowCo"])
        # LowCo 2021 (score=2) and 2022 (score=3) both have forward years
        assert result["low"]["sample_size"] == 2

    def test_last_year_excluded(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        # 2023 is the last year for both companies -> no forward year -> excluded
        # 2021 and 2022 contribute 1 record each per company = 4 total
        result = run_piotroski_backtest(["HighCo", "LowCo"])
        assert result["total_observations"] == 4

    def test_empty_company_list(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest([])
        assert result["total_observations"] == 0

    def test_unknown_company_contributes_zero(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["NonexistentCorp"])
        assert result["total_observations"] == 0

    def test_highco_positive_avg_revenue_growth(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["HighCo"])
        assert result["high"]["avg_revenue_growth"] > 0

    def test_lowco_negative_avg_revenue_growth(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["LowCo"])
        assert result["low"]["avg_revenue_growth"] < 0

    def test_highco_positive_avg_net_income_growth(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["HighCo"])
        assert result["high"]["avg_net_income_growth"] > 0

    def test_lowco_negative_avg_net_income_growth(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["LowCo"])
        assert result["low"]["avg_net_income_growth"] < 0

    def test_deterministic(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        r1 = run_piotroski_backtest(["HighCo", "LowCo"])
        r2 = run_piotroski_backtest(["HighCo", "LowCo"])
        assert r1 == r2

    def test_confidence_label_is_valid(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        result = run_piotroski_backtest(["HighCo", "LowCo"])
        assert result["confidence_label"] in ("low", "medium", "high")

    def test_4_observations_give_confidence_0_5(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        # 4 records: 3 <= 4 < 8 -> confidence = 0.5
        result = run_piotroski_backtest(["HighCo", "LowCo"])
        assert result["total_observations"] == 4
        assert result["confidence"] == 0.5

    def test_medium_bucket_empty_when_no_medium_scores(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        # HighCo scores: 7/7/8 (all high), LowCo: 2/3/2 (all low)
        result = run_piotroski_backtest(["HighCo", "LowCo"])
        assert result["medium"]["sample_size"] == 0
        assert result["medium"]["avg_revenue_growth"] is None

    def test_aggregation_independent_of_company_order(self, backtest_db):
        from ace_research.backtest import run_piotroski_backtest
        r1 = run_piotroski_backtest(["HighCo", "LowCo"])
        r2 = run_piotroski_backtest(["LowCo", "HighCo"])
        # Bucket stats must be identical regardless of company iteration order
        assert r1["high"]["sample_size"] == r2["high"]["sample_size"]
        assert r1["low"]["sample_size"]  == r2["low"]["sample_size"]
        assert r1["total_observations"]  == r2["total_observations"]


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
