"""
tests/test_report_pdf.py

Tests for ace_research/report_pdf.py (ReportLab Platypus PDF generator).

No database fixtures required.  All functions read only from supplied dicts.
generate_pdf() creates a real PDF; binary header confirms the format.
"""

import copy
import os
from unittest.mock import MagicMock, patch

import pytest

import ace_research.report_pdf as pdf_module


# =============================================================================
# Shared test data
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
        "total_liabilities": {"values": {2022: 800.0,  2023: 900.0}},
        "total_equity":      {"values": {2022: 1200.0, 2023: 1300.0}},
    },
    "quality_metrics": {
        "gross_margin":      {"values": {2022: 0.40, 2023: 0.42}},
        "operating_margin":  {"values": {2022: 0.20, 2023: 0.21}},
        "net_margin":        {"values": {2022: 0.15, 2023: 0.16}},
        "current_ratio":     {"values": {2022: 2.0,  2023: 2.1}},
        "piotroski_score":   {"values": {2022: 6,    2023: 7}},
        "risk_flags": [],
    },
}

SAMPLE_NARRATIVE = (
    "Executive Overview: TestCo financial performance for 2022-2023. "
    "Revenue increased to 1,100 (+10.0% YoY). "
    "Net income increased (+10.0% YoY). "
    "Operating Margin improved year-over-year. "
    "Financial health as measured by the Piotroski F-Score improved (latest: 7/9). "
    "No financial risk flags were detected for 2023."
)


# =============================================================================
# Format helpers  (pure functions, no ReportLab needed)
# =============================================================================

class TestFormatHelpers:
    # ── _fmt_num ──────────────────────────────────────────────────────────────
    def test_fmt_num_large_positive(self):
        assert pdf_module._fmt_num(1100.0) == "1,100"

    def test_fmt_num_large_negative(self):
        assert pdf_module._fmt_num(-2000.0) == "-2,000"

    def test_fmt_num_small_positive(self):
        assert pdf_module._fmt_num(0.5) == "0.50"

    def test_fmt_num_none(self):
        assert pdf_module._fmt_num(None) == "N/A"

    def test_fmt_num_exactly_1000(self):
        assert pdf_module._fmt_num(1000.0) == "1,000"

    # ── _fmt_pct ──────────────────────────────────────────────────────────────
    def test_fmt_pct_normal(self):
        assert pdf_module._fmt_pct(0.42) == "42.00%"

    def test_fmt_pct_zero(self):
        assert pdf_module._fmt_pct(0.0) == "0.00%"

    def test_fmt_pct_none(self):
        assert pdf_module._fmt_pct(None) == "N/A"

    # ── _fmt_ratio ────────────────────────────────────────────────────────────
    def test_fmt_ratio_normal(self):
        assert pdf_module._fmt_ratio(2.1) == "2.1000"

    def test_fmt_ratio_none(self):
        assert pdf_module._fmt_ratio(None) == "N/A"

    # ── _fmt_yoy ──────────────────────────────────────────────────────────────
    def test_fmt_yoy_positive(self):
        assert pdf_module._fmt_yoy(10.0) == "+10.00%"

    def test_fmt_yoy_negative(self):
        assert pdf_module._fmt_yoy(-5.0) == "-5.00%"

    def test_fmt_yoy_none(self):
        assert pdf_module._fmt_yoy(None) == "N/A"

    # ── _fmt_score ────────────────────────────────────────────────────────────
    def test_fmt_score_int(self):
        assert pdf_module._fmt_score(7) == "7"

    def test_fmt_score_none(self):
        assert pdf_module._fmt_score(None) == "N/A"


# =============================================================================
# generate_pdf — file creation
# =============================================================================

class TestGeneratePdf:
    def test_creates_file_on_disk(self, tmp_path):
        output = str(tmp_path / "report.pdf")
        pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)
        assert os.path.exists(output)

    def test_created_file_is_valid_pdf(self, tmp_path):
        output = str(tmp_path / "report.pdf")
        pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)
        with open(output, "rb") as fh:
            assert fh.read(4) == b"%PDF"

    def test_file_is_non_empty(self, tmp_path):
        output = str(tmp_path / "report.pdf")
        pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)
        assert os.path.getsize(output) > 0

    def test_raises_import_error_when_reportlab_absent(self, tmp_path):
        output = str(tmp_path / "missing.pdf")
        with patch.object(pdf_module, "_REPORTLAB_AVAILABLE", False):
            with pytest.raises(ImportError, match="reportlab"):
                pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)

    def test_error_message_mentions_pip_install(self, tmp_path):
        output = str(tmp_path / "missing.pdf")
        with patch.object(pdf_module, "_REPORTLAB_AVAILABLE", False):
            with pytest.raises(ImportError, match="pip install reportlab"):
                pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)

    def test_no_db_calls(self, tmp_path):
        output = str(tmp_path / "report.pdf")
        fake_db = MagicMock()
        with patch.dict("sys.modules", {"ace_research.db": fake_db}):
            pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)
        fake_db.get_canonical_financial_fact.assert_not_called()

    def test_works_with_empty_years(self, tmp_path):
        output = str(tmp_path / "empty.pdf")
        empty = {
            "company": "X", "years": [],
            "income_statement": {}, "balance_sheet": {}, "quality_metrics": {},
        }
        pdf_module.generate_pdf(empty, "Short narrative.", output)
        assert os.path.exists(output)

    def test_works_with_single_year(self, tmp_path):
        output = str(tmp_path / "single.pdf")
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["years"] = [2023]
        pdf_module.generate_pdf(s, SAMPLE_NARRATIVE, output)
        with open(output, "rb") as fh:
            assert fh.read(4) == b"%PDF"

    def test_works_with_risk_flags(self, tmp_path):
        output = str(tmp_path / "risk.pdf")
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["quality_metrics"]["risk_flags"] = ["Margin compression", "Rising leverage"]
        pdf_module.generate_pdf(s, SAMPLE_NARRATIVE, output)
        with open(output, "rb") as fh:
            assert fh.read(4) == b"%PDF"

    def test_missing_income_data_does_not_crash(self, tmp_path):
        output = str(tmp_path / "noincome.pdf")
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"] = {}
        pdf_module.generate_pdf(s, SAMPLE_NARRATIVE, output)
        assert os.path.exists(output)

    def test_none_values_produce_na_cells(self, tmp_path):
        output = str(tmp_path / "na.pdf")
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["values"] = {2022: None, 2023: None}
        pdf_module.generate_pdf(s, SAMPLE_NARRATIVE, output)
        assert os.path.exists(output)

    def test_three_years_does_not_crash(self, tmp_path):
        output = str(tmp_path / "three.pdf")
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["years"] = [2021, 2022, 2023]
        for section in ("income_statement", "balance_sheet"):
            for entry in s[section].values():
                entry["values"][2021] = 900.0
        for entry in s["quality_metrics"].values():
            if isinstance(entry, dict) and "values" in entry:
                entry["values"][2021] = entry["values"].get(2022)
        pdf_module.generate_pdf(s, SAMPLE_NARRATIVE, output)
        with open(output, "rb") as fh:
            assert fh.read(4) == b"%PDF"


# =============================================================================
# Module guarantees
# =============================================================================

class TestModuleGuarantees:
    def test_reportlab_available_is_bool(self):
        assert isinstance(pdf_module._REPORTLAB_AVAILABLE, bool)

    def test_generate_pdf_is_callable(self):
        assert callable(pdf_module.generate_pdf)

    def test_module_has_no_weasyprint_dependency(self):
        """After the rewrite, WeasyPrint must not appear anywhere in the module."""
        import inspect
        src = inspect.getsource(pdf_module)
        assert "weasyprint" not in src.lower()

    def test_fmt_helpers_importable_without_reportlab(self):
        """Pure format helpers work regardless of ReportLab availability."""
        assert pdf_module._fmt_num(1234.0) == "1,234"
        assert pdf_module._fmt_pct(0.5) == "50.00%"
        assert pdf_module._fmt_ratio(1.5) == "1.5000"
        assert pdf_module._fmt_yoy(5.0) == "+5.00%"
        assert pdf_module._fmt_score(9) == "9"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
