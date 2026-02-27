"""
tests/test_report_pdf.py

Tests for ace_research/report_pdf.py

render_html_report() is tested without any DB fixtures — pure dict input.
generate_pdf() is tested via a mocked WeasyPrint so the suite runs
regardless of whether the library is installed.
"""

import copy
import os
import pytest
from unittest.mock import patch, MagicMock


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
        "gross_margin":     {"values": {2022: 0.40, 2023: 0.42}},
        "operating_margin": {"values": {2022: 0.20, 2023: 0.21}},
        "net_margin":       {"values": {2022: 0.15, 2023: 0.16}},
        "current_ratio":    {"values": {2022: 2.0,  2023: 2.1}},
        "piotroski_score":  {"values": {2022: 6,    2023: 7}},
        "risk_flags": [],
    },
}

SAMPLE_NARRATIVE = (
    "Executive Overview: TestCo financial performance for 2022-2023. "
    "Revenue increased to 1,100 (+10.0% YoY). "
    "No financial risk flags were detected for 2023."
)


# =============================================================================
# Format helpers
# =============================================================================

class TestFormatHelpers:
    def test_fmt_num_large_value(self):
        from ace_research.report_pdf import _fmt_num
        assert _fmt_num(1100.0) == "1,100"

    def test_fmt_num_small_value(self):
        from ace_research.report_pdf import _fmt_num
        assert _fmt_num(0.5) == "0.50"

    def test_fmt_num_none(self):
        from ace_research.report_pdf import _fmt_num
        assert _fmt_num(None) == "N/A"

    def test_fmt_pct_standard(self):
        from ace_research.report_pdf import _fmt_pct
        assert _fmt_pct(0.25) == "25.00%"

    def test_fmt_pct_none(self):
        from ace_research.report_pdf import _fmt_pct
        assert _fmt_pct(None) == "N/A"

    def test_fmt_ratio(self):
        from ace_research.report_pdf import _fmt_ratio
        assert _fmt_ratio(2.1) == "2.1000"

    def test_fmt_yoy_positive(self):
        from ace_research.report_pdf import _fmt_yoy
        assert _fmt_yoy(10.0) == "+10.00%"

    def test_fmt_yoy_negative(self):
        from ace_research.report_pdf import _fmt_yoy
        assert _fmt_yoy(-5.0) == "-5.00%"

    def test_fmt_yoy_none(self):
        from ace_research.report_pdf import _fmt_yoy
        assert _fmt_yoy(None) == "N/A"

    def test_yoy_css_class_positive(self):
        from ace_research.report_pdf import _yoy_css_class
        assert _yoy_css_class(5.0) == "yoy-pos"

    def test_yoy_css_class_negative(self):
        from ace_research.report_pdf import _yoy_css_class
        assert _yoy_css_class(-3.0) == "yoy-neg"

    def test_yoy_css_class_none(self):
        from ace_research.report_pdf import _yoy_css_class
        assert _yoy_css_class(None) == "yoy-neutral"

    def test_e_escapes_ampersand(self):
        from ace_research.report_pdf import _e
        assert _e("A & B") == "A &amp; B"

    def test_e_escapes_angle_brackets(self):
        from ace_research.report_pdf import _e
        assert _e("<script>") == "&lt;script&gt;"


# =============================================================================
# render_html_report — document structure
# =============================================================================

class TestRenderHtmlReportStructure:
    def test_returns_string(self):
        from ace_research.report_pdf import render_html_report
        assert isinstance(render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE), str)

    def test_has_doctype(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "<!DOCTYPE html>" in result

    def test_has_html_open_and_close(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "<html" in result and "</html>" in result

    def test_has_head_and_body(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "<head>" in result
        assert "<body>" in result

    def test_has_inline_style_tag(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "<style>" in result

    def test_has_table_tags(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "<table>" in result

    def test_has_thead_and_tbody(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "<thead>" in result
        assert "<tbody>" in result

    def test_deterministic(self):
        from ace_research.report_pdf import render_html_report
        r1 = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        r2 = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert r1 == r2

    def test_empty_years_does_not_crash(self):
        from ace_research.report_pdf import render_html_report
        empty = {
            "company": "X", "years": [],
            "income_statement": {}, "balance_sheet": {}, "quality_metrics": {},
        }
        result = render_html_report(empty, "No data.")
        assert isinstance(result, str)


# =============================================================================
# render_html_report — content correctness
# =============================================================================

class TestRenderHtmlReportContent:
    def test_contains_company_name(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "TestCo" in result

    def test_contains_year(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "2023" in result

    def test_contains_executive_overview_section(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Executive Overview" in result

    def test_contains_narrative_text(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "TestCo financial performance" in result

    def test_contains_income_statement_section(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Income Statement" in result

    def test_contains_balance_sheet_section(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Balance Sheet" in result

    def test_contains_financial_quality_section(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Financial Quality" in result

    def test_revenue_label_present(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Revenue" in result

    def test_net_income_label_present(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Net Income" in result

    def test_total_assets_label_present(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Total Assets" in result

    def test_piotroski_label_present(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "Piotroski" in result

    def test_none_value_renders_as_na(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["values"][2023] = None
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert "N/A" in result

    def test_yoy_positive_shows_plus_sign(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "+10.00%" in result

    def test_yoy_negative_shows_minus_sign(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["yoy_pct"] = -5.0
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert "-5.00%" in result

    def test_yoy_positive_has_green_css_class(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "yoy-pos" in result

    def test_yoy_negative_has_red_css_class(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["yoy_pct"] = -5.0
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert "yoy-neg" in result

    def test_gross_margin_displayed_as_percentage(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        # gross_margin 0.42 -> 42.00%
        assert "42.00%" in result

    def test_current_ratio_displayed_as_decimal(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        # current_ratio 2.1 -> 2.1000
        assert "2.1000" in result

    def test_piotroski_score_value_present(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert ">7<" in result or ">7 " in result or "7</td>" in result

    def test_no_risk_message_when_flags_empty(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        assert "No financial risk flags detected" in result

    def test_risk_flag_names_shown_when_present(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["quality_metrics"]["risk_flags"] = ["Margin compression", "Rising financial leverage"]
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert "Margin compression" in result
        assert "Rising financial leverage" in result

    def test_risk_flags_sorted_alphabetically(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["quality_metrics"]["risk_flags"] = ["Zebra risk", "Alpha risk"]
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert result.index("Alpha risk") < result.index("Zebra risk")

    def test_html_escapes_company_name_special_chars(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["company"] = "A & B Corp"
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert "&amp;" in result

    def test_total_row_class_applied_to_net_income(self):
        from ace_research.report_pdf import render_html_report
        result = render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)
        # Net Income is the last income metric -> total-row class
        assert 'class="total-row"' in result

    def test_three_year_summary_has_three_year_columns(self):
        from ace_research.report_pdf import render_html_report
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["years"] = [2021, 2022, 2023]
        s["income_statement"]["revenue"]["values"][2021] = 900.0
        result = render_html_report(s, SAMPLE_NARRATIVE)
        assert "<th>2021</th>" in result
        assert "<th>2022</th>" in result
        assert "<th>2023</th>" in result


# =============================================================================
# generate_pdf — behaviour
# =============================================================================

class TestGeneratePdf:
    """Tests for generate_pdf() using a mocked WeasyPrint."""

    def _make_mocks(self):
        mock_cls  = MagicMock()
        mock_inst = MagicMock()
        mock_cls.return_value = mock_inst
        return mock_cls, mock_inst

    def test_raises_import_error_when_weasyprint_unavailable(self):
        import ace_research.report_pdf as pdf_module
        with patch.object(pdf_module, "_WEASYPRINT_AVAILABLE", False):
            with pytest.raises(ImportError, match="WeasyPrint"):
                pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, "/tmp/out.pdf")

    def test_calls_weasyprint_html_with_string_kwarg(self, tmp_path):
        import ace_research.report_pdf as pdf_module
        mock_cls, mock_inst = self._make_mocks()
        output = str(tmp_path / "report.pdf")

        with patch.object(pdf_module, "_WeasyHTML", mock_cls), \
             patch.object(pdf_module, "_WEASYPRINT_AVAILABLE", True):
            pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)

        mock_cls.assert_called_once()
        _, kwargs = mock_cls.call_args
        assert "string" in kwargs
        assert isinstance(kwargs["string"], str)

    def test_calls_write_pdf_with_correct_output_path(self, tmp_path):
        import ace_research.report_pdf as pdf_module
        mock_cls, mock_inst = self._make_mocks()
        output = str(tmp_path / "report.pdf")

        with patch.object(pdf_module, "_WeasyHTML", mock_cls), \
             patch.object(pdf_module, "_WEASYPRINT_AVAILABLE", True):
            pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)

        mock_inst.write_pdf.assert_called_once_with(output)

    def test_html_passed_to_weasyprint_contains_company(self, tmp_path):
        import ace_research.report_pdf as pdf_module
        mock_cls, mock_inst = self._make_mocks()
        output = str(tmp_path / "report.pdf")

        with patch.object(pdf_module, "_WeasyHTML", mock_cls), \
             patch.object(pdf_module, "_WEASYPRINT_AVAILABLE", True):
            pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)

        _, kwargs = mock_cls.call_args
        assert "TestCo" in kwargs["string"]

    def test_html_passed_contains_income_statement_section(self, tmp_path):
        import ace_research.report_pdf as pdf_module
        mock_cls, mock_inst = self._make_mocks()
        output = str(tmp_path / "report.pdf")

        with patch.object(pdf_module, "_WeasyHTML", mock_cls), \
             patch.object(pdf_module, "_WEASYPRINT_AVAILABLE", True):
            pdf_module.generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)

        _, kwargs = mock_cls.call_args
        assert "Income Statement" in kwargs["string"]


# =============================================================================
# Module-level guarantees
# =============================================================================

class TestModuleGuarantees:
    def test_module_importable_without_weasyprint(self):
        """render_html_report is available even when WeasyPrint is absent."""
        import ace_research.report_pdf as pdf_module
        assert hasattr(pdf_module, "render_html_report")
        assert hasattr(pdf_module, "generate_pdf")

    def test_render_html_report_makes_no_db_calls(self):
        """render_html_report must not import or call any DB helpers."""
        import ace_research.report_pdf as pdf_module

        # Patch the entire db module to detect unexpected calls
        fake_db = MagicMock()
        with patch.dict("sys.modules", {"ace_research.db": fake_db}):
            html = pdf_module.render_html_report(SAMPLE_SUMMARY, SAMPLE_NARRATIVE)

        # DB module was never actually called through render_html_report
        fake_db.get_canonical_financial_fact.assert_not_called()
        fake_db.get_metric_ratio.assert_not_called()

    def test_render_html_report_minimal_summary(self):
        """Minimal summary (only required keys, all None values) must not crash."""
        from ace_research.report_pdf import render_html_report
        minimal = {
            "company": "MinCo",
            "years": [2023],
            "income_statement": {
                "revenue":          {"values": {2023: None}, "yoy_pct": None},
                "operating_income": {"values": {2023: None}, "yoy_pct": None},
                "net_income":       {"values": {2023: None}, "yoy_pct": None},
            },
            "balance_sheet": {
                "total_assets":      {"values": {2023: None}},
                "total_liabilities": {"values": {2023: None}},
                "total_equity":      {"values": {2023: None}},
            },
            "quality_metrics": {
                "gross_margin":     {"values": {2023: None}},
                "operating_margin": {"values": {2023: None}},
                "net_margin":       {"values": {2023: None}},
                "current_ratio":    {"values": {2023: None}},
                "piotroski_score":  {"values": {2023: None}},
                "risk_flags": [],
            },
        }
        result = render_html_report(minimal, "No data available.")
        assert "MinCo" in result
        assert "N/A" in result


# =============================================================================
# Conditional real-PDF test (skipped when WeasyPrint is not installed)
# =============================================================================

@pytest.mark.skipif(
    not pytest.importorskip("weasyprint", reason="WeasyPrint not installed") if False else
    __import__("importlib.util", fromlist=["find_spec"]).find_spec("weasyprint") is None,
    reason="WeasyPrint not installed",
)
def test_pdf_file_created_on_disk(tmp_path):
    """End-to-end: a real PDF file is written when WeasyPrint is available."""
    from ace_research.report_pdf import generate_pdf
    output = str(tmp_path / "report.pdf")
    generate_pdf(SAMPLE_SUMMARY, SAMPLE_NARRATIVE, output)
    assert os.path.exists(output)
    assert os.path.getsize(output) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
