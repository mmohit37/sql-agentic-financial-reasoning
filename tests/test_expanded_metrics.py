"""
tests/test_expanded_metrics.py

Tests for Phase A (bullet executive overview) and Phase B (expanded derived metrics).

Phase A:
    TestBulletOverviewFormat — _SYSTEM_PROMPT directs the LLM to produce bullet output

Phase B:
    TestExpandedMetricsComputation  — new metrics computed correctly from DB values
    TestExpandedMetricsMissingInput — missing inputs yield None (not a crash)
    TestExpandedMetricsFallbackEquity — ROE uses equity derived from assets - liabilities
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest


# =============================================================================
# Phase A — Bullet Executive Overview
# =============================================================================

class TestBulletOverviewFormat:
    """The system prompt must instruct Claude to produce bullet output."""

    def test_system_prompt_requests_bullets(self):
        import ace_research.narrative_llm as m
        prompt_lower = m._SYSTEM_PROMPT.lower()
        assert "bullet" in prompt_lower

    def test_system_prompt_contains_bullet_character(self):
        import ace_research.narrative_llm as m
        # Unicode bullet (U+2022) or ASCII hyphen-based instruction
        assert "\u2022" in m._SYSTEM_PROMPT or "bullet points" in m._SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_executive_overview_header(self):
        import ace_research.narrative_llm as m
        assert "Executive Overview" in m._SYSTEM_PROMPT

    def test_system_prompt_covers_revenue(self):
        import ace_research.narrative_llm as m
        assert "revenue" in m._SYSTEM_PROMPT.lower()

    def test_system_prompt_covers_profitability(self):
        import ace_research.narrative_llm as m
        assert "profitab" in m._SYSTEM_PROMPT.lower()

    def test_system_prompt_covers_liquidity(self):
        import ace_research.narrative_llm as m
        assert "liquidity" in m._SYSTEM_PROMPT.lower()

    def test_system_prompt_covers_leverage(self):
        import ace_research.narrative_llm as m
        assert "leverage" in m._SYSTEM_PROMPT.lower()

    def test_system_prompt_prohibits_paragraphs(self):
        import ace_research.narrative_llm as m
        assert "paragraph" in m._SYSTEM_PROMPT.lower()

    def test_system_prompt_prohibits_inventing_numbers(self):
        import ace_research.narrative_llm as m
        assert "invent" in m._SYSTEM_PROMPT.lower() or "do not" in m._SYSTEM_PROMPT.lower()

    def test_api_call_passes_system_prompt(self):
        """generate_llm_summary must pass _SYSTEM_PROMPT as the system parameter."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        import ace_research.narrative_llm as m

        block = SimpleNamespace(type="text", text="• Revenue grew.")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(content=[block])

        summary = {
            "company": "Acme", "years": [2023],
            "income_statement": {
                "revenue": {"values": {2023: 100.0}, "yoy_pct": None},
                "operating_income": {"values": {2023: 20.0}, "yoy_pct": None},
                "net_income": {"values": {2023: 15.0}, "yoy_pct": None},
            },
            "balance_sheet": {
                "total_assets": {"values": {2023: 200.0}},
                "total_liabilities": {"values": {2023: 80.0}},
                "total_equity": {"values": {2023: 120.0}},
            },
            "quality_metrics": {
                "gross_margin": {"values": {2023: 0.4}},
                "operating_margin": {"values": {2023: 0.2}},
                "net_margin": {"values": {2023: 0.15}},
                "current_ratio": {"values": {2023: 2.0}},
                "piotroski_score": {"values": {2023: 7}},
                "risk_flags": [],
            },
        }

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            m.generate_llm_summary(summary, [2023])

        kwargs = mock_client.messages.create.call_args[1]
        assert kwargs["system"] == m._SYSTEM_PROMPT


# =============================================================================
# Phase B — Expanded Derived Metrics
# =============================================================================

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


def _insert_facts(cur, company, year, facts: dict):
    for metric, value in facts.items():
        cur.execute(
            "INSERT INTO financial_facts (company, year, metric, value) VALUES (?, ?, ?, ?)",
            (company, year, metric, value),
        )


def _insert_piotroski(cur, company, year, score):
    provenance = json.dumps({"total_score": score, "max_possible": 9, "signal_scores": {}})
    cur.execute(
        "INSERT INTO derived_metrics "
        "(company, year, metric, value, metric_type, input_components) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (company, year, "piotroski_f_score", float(score), "piotroski", provenance),
    )


# Full-featured company with all metrics present
_FULL_FACTS = {
    "revenue": 200.0, "operating_income": 40.0, "net_income": 20.0,
    "gross_profit": 80.0,
    "total_assets": 500.0, "total_liabilities": 300.0, "total_equity": 200.0,
    "current_assets": 150.0, "current_liabilities": 75.0,
}


@pytest.fixture
def expanded_db():
    """Temp DB with FullCo (all metrics) and SparseCo (no balance sheet metrics)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    # FullCo: all metrics available in 2023
    _insert_facts(cur, "FullCo", 2023, _FULL_FACTS)
    _insert_piotroski(cur, "FullCo", 2023, 7)

    # SparseCo: only revenue and net_income — no balance sheet metrics at all
    _insert_facts(cur, "SparseCo", 2023, {"revenue": 100.0, "net_income": 10.0})
    _insert_piotroski(cur, "SparseCo", 2023, 4)

    # NoEquityCo: has assets and liabilities but NOT total_equity (tests fallback ROE)
    _insert_facts(cur, "NoEquityCo", 2023, {
        "revenue": 150.0, "net_income": 15.0,
        "total_assets": 400.0, "total_liabilities": 250.0,
        "current_assets": 100.0, "current_liabilities": 50.0,
    })
    _insert_piotroski(cur, "NoEquityCo", 2023, 5)

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


class TestExpandedMetricsComputation:
    """New derived metrics compute to the correct values when all inputs are present."""

    def test_asset_turnover_computed(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        val = s["quality_metrics"]["asset_turnover"]["values"][2023]
        # 200 / 500 = 0.4
        assert val == pytest.approx(0.4)

    def test_return_on_assets_computed(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        val = s["quality_metrics"]["return_on_assets"]["values"][2023]
        # 20 / 500 = 0.04
        assert val == pytest.approx(0.04)

    def test_return_on_equity_computed(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        val = s["quality_metrics"]["return_on_equity"]["values"][2023]
        # 20 / 200 = 0.1
        assert val == pytest.approx(0.1)

    def test_debt_ratio_computed(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        val = s["quality_metrics"]["debt_ratio"]["values"][2023]
        # 300 / 500 = 0.6
        assert val == pytest.approx(0.6)

    def test_quick_ratio_computed(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        val = s["quality_metrics"]["quick_ratio"]["values"][2023]
        # 150 / 75 = 2.0
        assert val == pytest.approx(2.0)

    def test_all_new_metric_keys_present(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        qm = s["quality_metrics"]
        for key in ("asset_turnover", "return_on_assets", "return_on_equity",
                    "debt_ratio", "quick_ratio"):
            assert key in qm, f"Missing key: {key}"

    def test_existing_metrics_unaffected(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("FullCo", [2023])
        qm = s["quality_metrics"]
        # current_ratio and gross_margin should still be present and correct
        assert qm["current_ratio"]["values"][2023] == pytest.approx(2.0)  # 150/75
        assert qm["gross_margin"]["values"][2023] == pytest.approx(0.4)   # 80/200


class TestExpandedMetricsMissingInput:
    """Missing canonical inputs must produce None, not errors."""

    def test_asset_turnover_none_when_no_assets(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("SparseCo", [2023])
        assert s["quality_metrics"]["asset_turnover"]["values"][2023] is None

    def test_roa_none_when_no_assets(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("SparseCo", [2023])
        assert s["quality_metrics"]["return_on_assets"]["values"][2023] is None

    def test_roe_none_when_no_equity_and_no_liabilities(self, expanded_db):
        """SparseCo has no assets/liabilities so equity fallback can't run either."""
        from ace_research.report import build_financial_summary
        s = build_financial_summary("SparseCo", [2023])
        assert s["quality_metrics"]["return_on_equity"]["values"][2023] is None

    def test_debt_ratio_none_when_no_assets(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("SparseCo", [2023])
        assert s["quality_metrics"]["debt_ratio"]["values"][2023] is None

    def test_quick_ratio_none_when_no_current_assets(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("SparseCo", [2023])
        assert s["quality_metrics"]["quick_ratio"]["values"][2023] is None

    def test_missing_inputs_do_not_raise(self, expanded_db):
        from ace_research.report import build_financial_summary
        # Must complete without exception even with sparse data
        s = build_financial_summary("SparseCo", [2023])
        assert s["company"] == "SparseCo"


class TestExpandedMetricsFallbackEquity:
    """ROE must use equity derived from assets - liabilities when total_equity absent from DB."""

    def test_roe_uses_fallback_equity(self, expanded_db):
        """NoEquityCo has no total_equity in DB; it must be derived (400-250=150)."""
        from ace_research.report import build_financial_summary
        s = build_financial_summary("NoEquityCo", [2023])
        # Derived equity = 400 - 250 = 150
        derived_equity = s["balance_sheet"]["total_equity"]["values"][2023]
        assert derived_equity == pytest.approx(150.0)
        # ROE = 15 / 150 = 0.1
        roe = s["quality_metrics"]["return_on_equity"]["values"][2023]
        assert roe == pytest.approx(0.1)

    def test_asset_turnover_independent_of_equity(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("NoEquityCo", [2023])
        # 150 / 400 = 0.375
        assert s["quality_metrics"]["asset_turnover"]["values"][2023] == pytest.approx(0.375)

    def test_debt_ratio_with_derived_equity_company(self, expanded_db):
        from ace_research.report import build_financial_summary
        s = build_financial_summary("NoEquityCo", [2023])
        # 250 / 400 = 0.625
        assert s["quality_metrics"]["debt_ratio"]["values"][2023] == pytest.approx(0.625)
