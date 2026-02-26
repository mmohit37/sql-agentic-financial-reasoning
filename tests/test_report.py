"""
tests/test_report.py

Unit tests for ace_research/report.py.

Coverage:
  A) Private format helpers (_fmt_num, _fmt_pct, _fmt_ratio, _fmt_yoy, _fmt_score)
  B) build_financial_summary() — structure and values
  C) render_financial_summary_cli() — output sections (uses inline summary dict)
  D) Integration — builder + renderer together
"""

import json
import os
import sqlite3
import tempfile

import pytest


# =============================================================================
# Inline summary dict for renderer tests (no DB required)
# =============================================================================

SAMPLE_SUMMARY = {
    "company": "TestCo",
    "years": [2022, 2023],
    "income_statement": {
        "revenue":          {"values": {2022: 1000.0, 2023: 1100.0}, "yoy_pct": 10.0},
        "operating_income": {"values": {2022: 200.0,  2023: 220.0},  "yoy_pct": 10.0},
        "net_income":       {"values": {2022: 150.0,  2023: 165.0},  "yoy_pct": 10.0},
    },
    "balance_sheet": {
        "total_assets":      {"values": {2022: 2000.0, 2023: 2200.0}},
        "total_liabilities": {"values": {2022: 800.0,  2023: 850.0}},
        "total_equity":      {"values": {2022: 1200.0, 2023: 1350.0}},
    },
    "quality_metrics": {
        "gross_margin":      {"values": {2022: 0.4,   2023: 0.4091}},
        "operating_margin":  {"values": {2022: 0.2,   2023: 0.2}},
        "net_margin":        {"values": {2022: 0.15,  2023: 0.15}},
        "current_ratio":     {"values": {2022: 2.0,   2023: 2.1875}},
        "piotroski_score":   {"values": {2022: 7,     2023: 7}},
        "risk_flags":        [],
    },
}


# =============================================================================
# DB fixture
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


# TestCo financial facts: all metrics needed for all 6 risk rules + derived ratios
TESTCO_FACTS = {
    2022: {
        "revenue": 1000.0, "operating_income": 200.0, "net_income": 150.0,
        "gross_profit": 400.0,
        "total_assets": 2000.0, "total_liabilities": 800.0, "total_equity": 1200.0,
        "current_assets": 600.0, "current_liabilities": 300.0,
        "long_term_debt": 200.0, "operating_cash_flow": 200.0,
    },
    2023: {
        "revenue": 1100.0, "operating_income": 220.0, "net_income": 165.0,
        "gross_profit": 450.0,
        "total_assets": 2200.0, "total_liabilities": 850.0, "total_equity": 1350.0,
        "current_assets": 700.0, "current_liabilities": 320.0,
        "long_term_debt": 190.0, "operating_cash_flow": 250.0,
    },
}

TESTCO_SCORES = {2022: (7, 9), 2023: (7, 9)}


@pytest.fixture
def report_db():
    """
    Temp DB with TestCo financial data across 2022-2023.

    Healthy company:
      - Revenue: 1000 → 1100 (+10%)
      - Operating income: 200 → 220 (+10%)
      - Net income: 150 → 165 (+10%)
      - No risk flags triggered (improving metrics, Piotroski = 7)
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)

    for year, metrics in TESTCO_FACTS.items():
        for metric, value in metrics.items():
            cur.execute(
                "INSERT INTO financial_facts (company, year, metric, value) "
                "VALUES (?, ?, ?, ?)",
                ("TestCo", year, metric, value),
            )

    for year, (score, max_possible) in TESTCO_SCORES.items():
        provenance = json.dumps({
            "total_score": score,
            "max_possible": max_possible,
            "signal_scores": {},
        })
        cur.execute(
            "INSERT INTO derived_metrics "
            "(company, year, metric, value, metric_type, input_components) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("TestCo", year, "piotroski_f_score", float(score), "piotroski", provenance),
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


# =============================================================================
# Part A: Private format helpers
# =============================================================================

class TestFormatHelpers:

    def test_fmt_num_large_value(self):
        from ace_research.report import _fmt_num
        assert _fmt_num(168088.0) == "168,088"

    def test_fmt_num_small_value(self):
        from ace_research.report import _fmt_num
        assert _fmt_num(3.14) == "3.14"

    def test_fmt_num_none(self):
        from ace_research.report import _fmt_num
        assert _fmt_num(None) == "N/A"

    def test_fmt_num_zero(self):
        from ace_research.report import _fmt_num
        assert _fmt_num(0.0) == "0.00"

    def test_fmt_pct_quarter(self):
        from ace_research.report import _fmt_pct
        assert _fmt_pct(0.25) == "25.00%"

    def test_fmt_pct_none(self):
        from ace_research.report import _fmt_pct
        assert _fmt_pct(None) == "N/A"

    def test_fmt_ratio_decimal(self):
        from ace_research.report import _fmt_ratio
        assert _fmt_ratio(2.0) == "2.0000"

    def test_fmt_ratio_none(self):
        from ace_research.report import _fmt_ratio
        assert _fmt_ratio(None) == "N/A"

    def test_fmt_yoy_positive(self):
        from ace_research.report import _fmt_yoy
        assert _fmt_yoy(10.0) == "+10.00%"

    def test_fmt_yoy_negative(self):
        from ace_research.report import _fmt_yoy
        assert _fmt_yoy(-5.5) == "-5.50%"

    def test_fmt_yoy_none(self):
        from ace_research.report import _fmt_yoy
        assert _fmt_yoy(None) == "N/A"

    def test_fmt_score_integer(self):
        from ace_research.report import _fmt_score
        assert _fmt_score(7) == "7"

    def test_fmt_score_none(self):
        from ace_research.report import _fmt_score
        assert _fmt_score(None) == "N/A"

    def test_yoy_pct_positive(self):
        from ace_research.report import _yoy_pct
        assert _yoy_pct(110.0, 100.0) == 10.0

    def test_yoy_pct_negative(self):
        from ace_research.report import _yoy_pct
        assert _yoy_pct(90.0, 100.0) == -10.0

    def test_yoy_pct_none_when_prior_missing(self):
        from ace_research.report import _yoy_pct
        assert _yoy_pct(110.0, None) is None

    def test_yoy_pct_none_when_prior_zero(self):
        from ace_research.report import _yoy_pct
        assert _yoy_pct(110.0, 0.0) is None

    def test_yoy_pct_uses_abs_prior_for_negative_base(self):
        from ace_research.report import _yoy_pct
        # Moving from loss -100 to profit 50: change = 150, |prior| = 100 -> +150%
        result = _yoy_pct(50.0, -100.0)
        assert result == 150.0


# =============================================================================
# Part B: build_financial_summary — structure
# =============================================================================

class TestBuildFinancialSummaryStructure:

    def test_returns_company_name(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["company"] == "TestCo"

    def test_returns_sorted_years(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2023, 2022])
        assert result["years"] == [2022, 2023]

    def test_income_statement_has_all_metrics(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        for m in ("revenue", "operating_income", "net_income"):
            assert m in result["income_statement"]

    def test_income_statement_entries_have_values_and_yoy(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        for m in ("revenue", "operating_income", "net_income"):
            entry = result["income_statement"][m]
            assert "values" in entry
            assert "yoy_pct" in entry

    def test_balance_sheet_has_all_metrics(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        for m in ("total_assets", "total_liabilities", "total_equity"):
            assert m in result["balance_sheet"]

    def test_quality_metrics_has_derived_metrics(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        for m in ("gross_margin", "operating_margin", "net_margin", "current_ratio"):
            assert m in result["quality_metrics"]

    def test_quality_metrics_has_piotroski_score(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert "piotroski_score" in result["quality_metrics"]

    def test_quality_metrics_has_risk_flags_list(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert "risk_flags" in result["quality_metrics"]
        assert isinstance(result["quality_metrics"]["risk_flags"], list)

    def test_empty_years_returns_empty_dicts(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [])
        assert result["years"] == []
        assert result["quality_metrics"]["risk_flags"] == []

    def test_single_year_yoy_is_none(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2023])
        assert result["income_statement"]["revenue"]["yoy_pct"] is None

    def test_required_top_level_keys(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        for key in ("company", "years", "income_statement", "balance_sheet", "quality_metrics"):
            assert key in result


# =============================================================================
# Part C: build_financial_summary — values
# =============================================================================

class TestBuildFinancialSummaryValues:

    def test_revenue_value_correct(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["income_statement"]["revenue"]["values"][2022] == 1000.0
        assert result["income_statement"]["revenue"]["values"][2023] == 1100.0

    def test_revenue_yoy_10_percent(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["income_statement"]["revenue"]["yoy_pct"] == 10.0

    def test_operating_income_yoy_10_percent(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["income_statement"]["operating_income"]["yoy_pct"] == 10.0

    def test_net_income_yoy_10_percent(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["income_statement"]["net_income"]["yoy_pct"] == 10.0

    def test_gross_margin_correct(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        gm_2022 = result["quality_metrics"]["gross_margin"]["values"][2022]
        # gross_profit=400 / revenue=1000 = 0.4
        assert abs(gm_2022 - 0.4) < 1e-6

    def test_operating_margin_correct(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        om_2022 = result["quality_metrics"]["operating_margin"]["values"][2022]
        # operating_income=200 / revenue=1000 = 0.2
        assert abs(om_2022 - 0.2) < 1e-6

    def test_net_margin_correct(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        nm_2022 = result["quality_metrics"]["net_margin"]["values"][2022]
        # net_income=150 / revenue=1000 = 0.15
        assert abs(nm_2022 - 0.15) < 1e-6

    def test_current_ratio_correct(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        cr_2022 = result["quality_metrics"]["current_ratio"]["values"][2022]
        # current_assets=600 / current_liabilities=300 = 2.0
        assert abs(cr_2022 - 2.0) < 1e-6

    def test_piotroski_score_from_cache(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["quality_metrics"]["piotroski_score"]["values"][2022] == 7
        assert result["quality_metrics"]["piotroski_score"]["values"][2023] == 7

    def test_risk_flags_no_flags_for_healthy_company(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        # TestCo has improving metrics -> no flags expected
        assert result["quality_metrics"]["risk_flags"] == []

    def test_unknown_company_values_are_none(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("UnknownCorp", [2022, 2023])
        assert result["income_statement"]["revenue"]["values"][2022] is None
        assert result["income_statement"]["revenue"]["yoy_pct"] is None

    def test_total_assets_value_correct(self, report_db):
        from ace_research.report import build_financial_summary
        result = build_financial_summary("TestCo", [2022, 2023])
        assert result["balance_sheet"]["total_assets"]["values"][2022] == 2000.0

    def test_deterministic(self, report_db):
        from ace_research.report import build_financial_summary
        r1 = build_financial_summary("TestCo", [2022, 2023])
        r2 = build_financial_summary("TestCo", [2022, 2023])
        assert r1 == r2


# =============================================================================
# Part D: render_financial_summary_cli — output validation
# =============================================================================

class TestRenderFinancialSummaryCLI:
    """Renderer tests use SAMPLE_SUMMARY (inline dict). No DB required."""

    def test_income_statement_section_header(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "INCOME STATEMENT" in out

    def test_balance_sheet_section_header(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "BALANCE SHEET" in out

    def test_financial_quality_section_header(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "FINANCIAL QUALITY" in out

    def test_company_name_in_output(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "TestCo" in out

    def test_years_in_output(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "2022" in out
        assert "2023" in out

    def test_revenue_label_in_output(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "Revenue" in out

    def test_piotroski_score_label_in_output(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "Piotroski Score" in out

    def test_risk_flags_section_in_output(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "Risk Flags" in out

    def test_yoy_pct_column_header_in_output(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "YoY %" in out

    def test_yoy_pct_value_shown_for_revenue(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "+10.00%" in out

    def test_no_flags_message_when_empty(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        assert "None detected" in out

    def test_risk_flags_message_when_flags_present(self, capsys):
        from ace_research.report import render_financial_summary_cli
        summary_with_flags = {
            **SAMPLE_SUMMARY,
            "quality_metrics": {
                **SAMPLE_SUMMARY["quality_metrics"],
                "risk_flags": ["Low earnings quality", "Margin compression"],
            },
        }
        render_financial_summary_cli(summary_with_flags)
        out = capsys.readouterr().out
        assert "Low earnings quality" in out
        assert "Margin compression" in out

    def test_gross_margin_displayed_as_percentage(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        # gross_margin=0.4 -> should show "40.00%"
        assert "40.00%" in out

    def test_current_ratio_displayed_as_decimal(self, capsys):
        from ace_research.report import render_financial_summary_cli
        render_financial_summary_cli(SAMPLE_SUMMARY)
        out = capsys.readouterr().out
        # current_ratio=2.0 -> "2.0000"
        assert "2.0000" in out

    def test_empty_years_does_not_crash(self, capsys):
        from ace_research.report import render_financial_summary_cli
        empty = {
            "company": "NoCo",
            "years": [],
            "income_statement": {},
            "balance_sheet": {},
            "quality_metrics": {"risk_flags": []},
        }
        render_financial_summary_cli(empty)  # must not raise
        out = capsys.readouterr().out
        assert "NoCo" in out


# =============================================================================
# Part E: Integration — builder + renderer
# =============================================================================

class TestReportIntegration:

    def test_end_to_end_no_crash(self, report_db, capsys):
        from ace_research.report import build_financial_summary, render_financial_summary_cli
        summary = build_financial_summary("TestCo", [2022, 2023])
        render_financial_summary_cli(summary)
        out = capsys.readouterr().out
        assert "TestCo" in out
        assert "INCOME STATEMENT" in out

    def test_builder_output_feeds_renderer_cleanly(self, report_db, capsys):
        from ace_research.report import build_financial_summary, render_financial_summary_cli
        summary = build_financial_summary("TestCo", [2022, 2023])
        render_financial_summary_cli(summary)
        out = capsys.readouterr().out
        # Revenue 1,000 and 1,100 should appear in output
        assert "1,000" in out
        assert "1,100" in out

    def test_renderer_shows_actual_yoy_from_builder(self, report_db, capsys):
        from ace_research.report import build_financial_summary, render_financial_summary_cli
        summary = build_financial_summary("TestCo", [2022, 2023])
        render_financial_summary_cli(summary)
        out = capsys.readouterr().out
        assert "+10.00%" in out


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])
