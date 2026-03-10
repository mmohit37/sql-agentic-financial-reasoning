"""
tests/test_compare.py

Tests for ace_research/compare.py.

Coverage:
    TestCompareCompanies    — compare_companies() happy path and sparse data
    TestRenderCLI           — render_comparison_cli() output format
    TestComparisonPDF       — generate_comparison_pdf() produces valid PDF file
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest


# =============================================================================
# Helpers — minimal DB + fixture
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


def _insert_facts(cur, company, year, facts):
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


_ALPHA_FACTS = {
    "revenue": 500.0, "operating_income": 100.0, "net_income": 80.0,
    "gross_profit": 300.0,
    "total_assets": 1000.0, "total_liabilities": 400.0, "total_equity": 600.0,
    "current_assets": 250.0, "current_liabilities": 100.0,
}
_BETA_FACTS = {
    "revenue": 200.0, "operating_income": 30.0, "net_income": 20.0,
    "gross_profit": 100.0,
    "total_assets": 600.0, "total_liabilities": 420.0, "total_equity": 180.0,
    "current_assets": 90.0, "current_liabilities": 80.0,
}


@pytest.fixture
def compare_db():
    """Temp DB with AlphaCo (strong) and BetaCo (weaker financials)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _create_tables(cur)
    _insert_facts(cur, "AlphaCo", 2023, _ALPHA_FACTS)
    _insert_piotroski(cur, "AlphaCo", 2023, 7)
    _insert_facts(cur, "BetaCo", 2023, _BETA_FACTS)
    _insert_piotroski(cur, "BetaCo", 2023, 4)
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
# TestCompareCompanies
# =============================================================================

class TestCompareCompanies:

    def test_returns_list(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo", "BetaCo"], 2023)
        assert isinstance(rows, list)

    def test_returns_one_row_per_company(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo", "BetaCo"], 2023)
        assert len(rows) == 2

    def test_row_has_required_keys(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo"], 2023)
        required = {"company", "revenue", "net_margin", "return_on_equity", "debt_ratio", "risk_level"}
        assert required.issubset(rows[0].keys())

    def test_company_name_matches(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo", "BetaCo"], 2023)
        names = [r["company"] for r in rows]
        assert "AlphaCo" in names
        assert "BetaCo" in names

    def test_revenue_is_numeric(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo"], 2023)
        assert rows[0]["revenue"] == pytest.approx(500.0)

    def test_net_margin_computed(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo"], 2023)
        # 80 / 500 = 0.16
        assert rows[0]["net_margin"] == pytest.approx(0.16)

    def test_roe_computed(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo"], 2023)
        # 80 / 600 ≈ 0.1333
        assert rows[0]["return_on_equity"] == pytest.approx(80 / 600)

    def test_debt_ratio_computed(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo"], 2023)
        # 400 / 1000 = 0.4
        assert rows[0]["debt_ratio"] == pytest.approx(0.4)

    def test_risk_level_is_string(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo"], 2023)
        assert isinstance(rows[0]["risk_level"], str)
        assert len(rows[0]["risk_level"]) > 0

    def test_unknown_company_returns_sparse_row(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["NonExistentCo"], 2023)
        assert len(rows) == 1
        r = rows[0]
        assert r["company"] == "NonExistentCo"
        assert r["revenue"] is None
        # risk engine runs on empty data and returns a level string (not a crash)
        assert isinstance(r["risk_level"], str)

    def test_mixed_known_unknown_companies(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["AlphaCo", "GhostCo"], 2023)
        assert len(rows) == 2
        names = [r["company"] for r in rows]
        assert "AlphaCo" in names
        assert "GhostCo" in names

    def test_order_preserved(self, compare_db):
        from ace_research.compare import compare_companies
        with patch("ace_research.orchestration.ensure_company_years_ready"):
            rows = compare_companies(["BetaCo", "AlphaCo"], 2023)
        assert rows[0]["company"] == "BetaCo"
        assert rows[1]["company"] == "AlphaCo"


# =============================================================================
# TestRenderCLI
# =============================================================================

class TestRenderCLI:

    _ROWS = [
        {"company": "AlphaCo", "revenue": 500.0, "net_margin": 0.16,
         "return_on_equity": 0.133, "debt_ratio": 0.4, "risk_level": "Low"},
        {"company": "BetaCo",  "revenue": 200.0, "net_margin": 0.10,
         "return_on_equity": 0.111, "debt_ratio": 0.7, "risk_level": "Moderate"},
    ]

    def _capture(self, year=2023):
        from ace_research.compare import render_comparison_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            render_comparison_cli(self._ROWS, year)
        return buf.getvalue()

    def test_output_contains_year(self):
        assert "2023" in self._capture()

    def test_output_contains_company_names(self):
        out = self._capture()
        assert "AlphaCo" in out
        assert "BetaCo" in out

    def test_output_contains_header(self):
        out = self._capture()
        assert "Revenue" in out
        assert "Net Margin" in out

    def test_output_contains_formatted_revenue(self):
        out = self._capture()
        # 500.0 → "500M" (or similar depending on scale in test data)
        assert "500" in out

    def test_output_contains_risk_level(self):
        out = self._capture()
        assert "Low" in out or "Moderate" in out

    def test_none_revenue_renders_na(self):
        from ace_research.compare import render_comparison_cli
        rows = [{"company": "X", "revenue": None, "net_margin": None,
                 "return_on_equity": None, "debt_ratio": None, "risk_level": "N/A"}]
        buf = io.StringIO()
        with redirect_stdout(buf):
            render_comparison_cli(rows, 2023)
        assert "N/A" in buf.getvalue()


# =============================================================================
# TestComparisonPDF
# =============================================================================

class TestComparisonPDF:

    _ROWS = [
        {"company": "AlphaCo", "revenue": 500.0, "net_margin": 0.16,
         "return_on_equity": 0.133, "debt_ratio": 0.4, "risk_level": "Low"},
        {"company": "BetaCo",  "revenue": 200.0, "net_margin": 0.10,
         "return_on_equity": 0.111, "debt_ratio": 0.7, "risk_level": "Moderate"},
    ]

    def test_pdf_file_created(self):
        from ace_research.compare import generate_comparison_pdf
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            generate_comparison_pdf(self._ROWS, 2023, path)
            assert os.path.isfile(path)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def test_pdf_has_pdf_header(self):
        from ace_research.compare import generate_comparison_pdf
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            generate_comparison_pdf(self._ROWS, 2023, path)
            with open(path, "rb") as f:
                assert f.read(4) == b"%PDF"
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def test_pdf_non_zero_size(self):
        from ace_research.compare import generate_comparison_pdf
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            generate_comparison_pdf(self._ROWS, 2023, path)
            assert os.path.getsize(path) > 0
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def test_pdf_raises_import_error_without_reportlab(self):
        import sys
        from unittest.mock import patch
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "reportlab.platypus":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        from ace_research.compare import generate_comparison_pdf
        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="ReportLab"):
                generate_comparison_pdf(self._ROWS, 2023, "/tmp/unused.pdf")
