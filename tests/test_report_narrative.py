"""
tests/test_report_narrative.py

Tests for ace_research/report_narrative.py

No database fixtures are needed: all functions are pure text generation
that read only from a supplied dict.
"""

import copy
import pytest


# =============================================================================
# Shared test data — mirrors the shape of build_financial_summary() output
# =============================================================================

SAMPLE_SUMMARY = {
    "company": "TestCo",
    "years": [2022, 2023],
    "income_statement": {
        "revenue": {"values": {2022: 1000.0, 2023: 1100.0}, "yoy_pct": 10.0},
        "operating_income": {"values": {2022: 200.0, 2023: 220.0}, "yoy_pct": 10.0},
        "net_income": {"values": {2022: 150.0, 2023: 165.0}, "yoy_pct": 10.0},
    },
    "balance_sheet": {
        "total_assets": {"values": {2022: 2000.0, 2023: 2200.0}},
        "total_liabilities": {"values": {2022: 800.0, 2023: 900.0}},
        "total_equity": {"values": {2022: 1200.0, 2023: 1300.0}},
    },
    "quality_metrics": {
        "gross_margin": {"values": {2022: 0.40, 2023: 0.42}},
        "operating_margin": {"values": {2022: 0.20, 2023: 0.21}},
        "net_margin": {"values": {2022: 0.15, 2023: 0.16}},
        "current_ratio": {"values": {2022: 2.0, 2023: 2.1}},
        "piotroski_score": {"values": {2022: 6, 2023: 7}},
        "risk_flags": [],
    },
}


# =============================================================================
# _direction helper
# =============================================================================

class TestDirectionHelper:
    def test_positive_yoy_returns_increased(self):
        from ace_research.report_narrative import _direction
        assert _direction(10.0) == "increased"

    def test_negative_yoy_returns_declined(self):
        from ace_research.report_narrative import _direction
        assert _direction(-5.0) == "declined"

    def test_none_returns_stable(self):
        from ace_research.report_narrative import _direction
        assert _direction(None) == "remained stable"

    def test_zero_returns_stable(self):
        from ace_research.report_narrative import _direction
        assert _direction(0.0) == "remained stable"

    def test_below_threshold_positive_returns_stable(self):
        from ace_research.report_narrative import _direction
        # 0.5 < 1.0 threshold
        assert _direction(0.5) == "remained stable"

    def test_below_threshold_negative_returns_stable(self):
        from ace_research.report_narrative import _direction
        assert _direction(-0.9) == "remained stable"

    def test_above_threshold_positive_returns_increased(self):
        from ace_research.report_narrative import _direction
        assert _direction(1.5) == "increased"


# =============================================================================
# _margin_direction helper
# =============================================================================

class TestMarginDirectionHelper:
    def test_improved_when_latest_higher(self):
        from ace_research.report_narrative import _margin_direction
        vals = {2022: 0.20, 2023: 0.25}
        assert _margin_direction(vals, [2022, 2023]) == "improved"

    def test_declined_when_latest_lower(self):
        from ace_research.report_narrative import _margin_direction
        vals = {2022: 0.25, 2023: 0.20}
        assert _margin_direction(vals, [2022, 2023]) == "declined"

    def test_stable_when_diff_is_zero(self):
        from ace_research.report_narrative import _margin_direction
        vals = {2022: 0.20, 2023: 0.20}
        assert _margin_direction(vals, [2022, 2023]) == "remained stable"

    def test_stable_when_single_year(self):
        from ace_research.report_narrative import _margin_direction
        vals = {2023: 0.20}
        assert _margin_direction(vals, [2023]) == "remained stable"

    def test_stable_when_prior_is_none(self):
        from ace_research.report_narrative import _margin_direction
        vals = {2022: None, 2023: 0.20}
        assert _margin_direction(vals, [2022, 2023]) == "remained stable"

    def test_stable_when_latest_is_none(self):
        from ace_research.report_narrative import _margin_direction
        vals = {2022: 0.20, 2023: None}
        assert _margin_direction(vals, [2022, 2023]) == "remained stable"


# =============================================================================
# _piotroski_trend helper
# =============================================================================

class TestPiotroskiTrendHelper:
    def test_improved_when_last_score_higher(self):
        from ace_research.report_narrative import _piotroski_trend
        vals = {2022: 5, 2023: 7}
        assert _piotroski_trend(vals, [2022, 2023]) == "improved"

    def test_declined_when_last_score_lower(self):
        from ace_research.report_narrative import _piotroski_trend
        vals = {2022: 7, 2023: 5}
        assert _piotroski_trend(vals, [2022, 2023]) == "declined"

    def test_stable_when_scores_equal(self):
        from ace_research.report_narrative import _piotroski_trend
        vals = {2022: 6, 2023: 6}
        assert _piotroski_trend(vals, [2022, 2023]) == "remained stable"

    def test_insufficient_data_single_year(self):
        from ace_research.report_narrative import _piotroski_trend
        vals = {2023: 6}
        assert _piotroski_trend(vals, [2023]) == "insufficient data"

    def test_insufficient_data_all_none(self):
        from ace_research.report_narrative import _piotroski_trend
        vals = {2022: None, 2023: None}
        assert _piotroski_trend(vals, [2022, 2023]) == "insufficient data"

    def test_skips_none_years(self):
        from ace_research.report_narrative import _piotroski_trend
        # 2022 has no score; 2023: 5, 2024: 8 -> improving
        vals = {2022: None, 2023: 5, 2024: 8}
        assert _piotroski_trend(vals, [2022, 2023, 2024]) == "improved"


# =============================================================================
# _fmt_revenue helper
# =============================================================================

class TestFmtRevenue:
    def test_large_value_uses_comma_separator(self):
        from ace_research.report_narrative import _fmt_revenue
        assert _fmt_revenue(1100.0) == "1,100"

    def test_small_value_uses_two_decimal_places(self):
        from ace_research.report_narrative import _fmt_revenue
        assert _fmt_revenue(0.5) == "0.50"

    def test_none_returns_na(self):
        from ace_research.report_narrative import _fmt_revenue
        assert _fmt_revenue(None) == "N/A"

    def test_large_negative_value(self):
        from ace_research.report_narrative import _fmt_revenue
        assert _fmt_revenue(-2000.0) == "-2,000"


# =============================================================================
# generate_deterministic_narrative — structure
# =============================================================================

class TestGenerateDeterministicNarrativeStructure:
    def test_starts_with_executive_overview(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert narrative.startswith("Executive Overview")

    def test_contains_company_name(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "TestCo" in narrative

    def test_contains_start_year(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "2022" in narrative

    def test_contains_end_year(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "2023" in narrative

    def test_sentence_count_within_range(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        # Split on ". " to avoid false splits inside numbers like "+10.0%"
        sentences = [s.strip() for s in narrative.split(". ") if s.strip()]
        assert 6 <= len(sentences) <= 10

    def test_returns_string(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        assert isinstance(generate_deterministic_narrative(SAMPLE_SUMMARY), str)

    def test_non_empty(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        assert len(generate_deterministic_narrative(SAMPLE_SUMMARY)) > 0

    def test_single_year_does_not_crash(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["years"] = [2023]
        s["income_statement"]["revenue"]["yoy_pct"] = None
        s["income_statement"]["net_income"]["yoy_pct"] = None
        narrative = generate_deterministic_narrative(s)
        assert "Executive Overview" in narrative

    def test_empty_years_does_not_crash(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        empty = {
            "company": "X", "years": [],
            "income_statement": {}, "balance_sheet": {}, "quality_metrics": {},
        }
        narrative = generate_deterministic_narrative(empty)
        assert "Executive Overview" in narrative

    def test_deterministic_same_output_twice(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        n1 = generate_deterministic_narrative(SAMPLE_SUMMARY)
        n2 = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert n1 == n2


# =============================================================================
# generate_deterministic_narrative — content
# =============================================================================

class TestGenerateDeterministicNarrativeContent:
    def test_revenue_increased_when_yoy_positive(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "Revenue increased" in narrative

    def test_revenue_declined_when_yoy_negative(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["yoy_pct"] = -5.0
        narrative = generate_deterministic_narrative(s)
        assert "Revenue declined" in narrative

    def test_revenue_stable_when_yoy_near_zero(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["yoy_pct"] = 0.3
        narrative = generate_deterministic_narrative(s)
        assert "Revenue remained stable" in narrative

    def test_revenue_latest_value_present(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "1,100" in narrative

    def test_yoy_pct_shown_with_sign(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "+10.0%" in narrative

    def test_net_income_increased_when_yoy_positive(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "Net income increased" in narrative

    def test_net_income_declined_when_yoy_negative(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["net_income"]["yoy_pct"] = -8.0
        narrative = generate_deterministic_narrative(s)
        assert "Net income declined" in narrative

    def test_operating_margin_improved_in_narrative(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        # operating_margin 0.20 -> 0.21 = improved; preferred over gross_margin
        assert "Operating Margin improved" in narrative

    def test_margin_declined_when_value_lower(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["quality_metrics"]["operating_margin"]["values"][2023] = 0.15
        narrative = generate_deterministic_narrative(s)
        assert "Operating Margin declined" in narrative

    def test_falls_back_to_gross_margin_when_operating_margin_absent(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        del s["quality_metrics"]["operating_margin"]
        narrative = generate_deterministic_narrative(s)
        assert "Gross Margin" in narrative

    def test_piotroski_trend_mentioned(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "Piotroski F-Score" in narrative

    def test_piotroski_improved_when_trend_up(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        # piotroski_score: 6 -> 7 = improved
        assert "improved" in narrative

    def test_piotroski_latest_score_shown(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "7/9" in narrative

    def test_no_risk_flags_message_when_empty(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        narrative = generate_deterministic_narrative(SAMPLE_SUMMARY)
        assert "No financial risk flags" in narrative

    def test_risk_flags_listed_when_present(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["quality_metrics"]["risk_flags"] = ["Margin compression", "Rising financial leverage"]
        narrative = generate_deterministic_narrative(s)
        assert "Margin compression" in narrative
        assert "Rising financial leverage" in narrative

    def test_risk_flags_sorted_alphabetically(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["quality_metrics"]["risk_flags"] = ["Zebra risk", "Alpha risk"]
        narrative = generate_deterministic_narrative(s)
        assert narrative.index("Alpha risk") < narrative.index("Zebra risk")

    def test_missing_revenue_handled_gracefully(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["revenue"]["values"] = {2022: None, 2023: None}
        narrative = generate_deterministic_narrative(s)
        assert "unavailable" in narrative

    def test_missing_net_income_handled_gracefully(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["income_statement"]["net_income"]["values"] = {2022: None, 2023: None}
        narrative = generate_deterministic_narrative(s)
        assert "unavailable" in narrative

    def test_piotroski_insufficient_data_when_single_year(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        s["years"] = [2023]
        s["quality_metrics"]["piotroski_score"]["values"] = {2023: 6}
        narrative = generate_deterministic_narrative(s)
        # Single year -> trend unavailable; latest score should still be mentioned
        assert "6/9" in narrative

    def test_no_margin_data_message(self):
        from ace_research.report_narrative import generate_deterministic_narrative
        s = copy.deepcopy(SAMPLE_SUMMARY)
        del s["quality_metrics"]["operating_margin"]
        del s["quality_metrics"]["gross_margin"]
        narrative = generate_deterministic_narrative(s)
        assert "unavailable" in narrative


# =============================================================================
# generate_narrative — dispatcher
# =============================================================================

class TestGenerateNarrativeDispatcher:
    def test_default_mode_matches_deterministic(self):
        from ace_research.report_narrative import generate_narrative, generate_deterministic_narrative
        assert generate_narrative(SAMPLE_SUMMARY) == generate_deterministic_narrative(SAMPLE_SUMMARY)

    def test_explicit_deterministic_mode(self):
        from ace_research.report_narrative import generate_narrative
        narrative = generate_narrative(SAMPLE_SUMMARY, mode="deterministic")
        assert narrative.startswith("Executive Overview")

    def test_unknown_mode_raises_not_implemented(self):
        from ace_research.report_narrative import generate_narrative
        with pytest.raises(NotImplementedError):
            generate_narrative(SAMPLE_SUMMARY, mode="gpt")

    def test_returns_string(self):
        from ace_research.report_narrative import generate_narrative
        assert isinstance(generate_narrative(SAMPLE_SUMMARY), str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
