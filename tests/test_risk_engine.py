"""
tests/test_risk_engine.py

Unit tests for ace_research/risk_engine.py.

All tests are pure — no DB, no filesystem. Input is a hand-crafted summary dict
that mirrors the shape produced by build_financial_summary().
"""

import pytest
from ace_research.risk_engine import (
    analyze_risk,
    _score_liquidity,
    _score_profitability,
    _score_revenue_stability,
    _score_leverage,
    _severity,
    _overall_level,
)


# =============================================================================
# Helpers
# =============================================================================

def _summary(
    cr_vals=None,
    nm_vals=None,
    rev_vals=None,
    ld_vals=None,
    eq_vals=None,
    years=None,
):
    """Build a minimal summary dict for testing."""
    cr_vals  = cr_vals  or {}
    nm_vals  = nm_vals  or {}
    rev_vals = rev_vals or {}
    eq_vals  = eq_vals  or {}
    bs = {
        "total_assets":      {"values": {}},
        "total_liabilities": {"values": {}},
        "total_equity":      {"values": eq_vals},
    }
    if ld_vals is not None:
        bs["long_term_debt"] = {"values": ld_vals}
    return {
        "company": "TestCo",
        "years":   sorted(years) if years else [],
        "income_statement": {
            "revenue": {"values": rev_vals},
        },
        "balance_sheet": bs,
        "quality_metrics": {
            "current_ratio": {"values": cr_vals},
            "net_margin":    {"values": nm_vals},
        },
    }


# =============================================================================
# _severity helper
# =============================================================================

class TestSeverity:
    def test_positive(self):  assert _severity(1)  == "positive"
    def test_positive_high(self): assert _severity(2)  == "positive"
    def test_stable(self):    assert _severity(0)  == "stable"
    def test_moderate(self):  assert _severity(-1) == "moderate"
    def test_elevated(self):  assert _severity(-2) == "elevated"
    def test_elevated_worse(self): assert _severity(-3) == "elevated"


# =============================================================================
# _overall_level helper
# =============================================================================

class TestOverallLevel:
    def test_elevated(self):  assert _overall_level(-4) == "Elevated"
    def test_elevated_low(self): assert _overall_level(-5) == "Elevated"
    def test_moderate_neg1(self): assert _overall_level(-1) == "Moderate"
    def test_moderate_neg3(self): assert _overall_level(-3) == "Moderate"
    def test_low_zero(self):  assert _overall_level(0)  == "Low"
    def test_low_two(self):   assert _overall_level(2)  == "Low"
    def test_strong(self):    assert _overall_level(3)  == "Strong"
    def test_strong_high(self): assert _overall_level(5) == "Strong"


# =============================================================================
# Liquidity scorer
# =============================================================================

class TestLiquidityScoring:

    def test_cr_below_1_gives_minus_2(self):
        # Single-year CR (no YoY adjustment possible) → only base penalty applies.
        s = _summary(cr_vals={2023: 0.8}, years=[2023])
        score, _ = _score_liquidity(s, 2023, [2023])
        assert score == -2

    def test_cr_below_1_3_gives_minus_1(self):
        # Small prior-year difference (~4% decline) — does not trigger YoY penalty.
        s = _summary(cr_vals={2022: 1.25, 2023: 1.2}, years=[2022, 2023])
        score, _ = _score_liquidity(s, 2023, [2022, 2023])
        assert score == -1

    def test_cr_yoy_decline_more_than_15pct(self):
        # CR 2.0 -> 1.5: decline of 25%, but CR >= 1.3, so base = 0, adjustment = -1
        s = _summary(cr_vals={2022: 2.0, 2023: 1.5}, years=[2022, 2023])
        score, _ = _score_liquidity(s, 2023, [2022, 2023])
        assert score == -1

    def test_cr_below_1_3_with_large_yoy_decline_gives_minus_2(self):
        # CR 1.5 -> 1.1: base -1 (< 1.3), decline (1.1-1.5)/1.5 = -26.7% -> -1 more = -2
        s = _summary(cr_vals={2022: 1.5, 2023: 1.1}, years=[2022, 2023])
        score, _ = _score_liquidity(s, 2023, [2022, 2023])
        assert score == -2

    def test_cr_above_2_5_stable_gives_plus_1(self):
        # CR 2.8, no meaningful change → base 0 + bonus +1
        s = _summary(cr_vals={2022: 2.7, 2023: 2.8}, years=[2022, 2023])
        score, _ = _score_liquidity(s, 2023, [2022, 2023])
        assert score == 1

    def test_cr_yoy_increase_more_than_15pct_gives_plus_1(self):
        s = _summary(cr_vals={2022: 1.5, 2023: 1.8}, years=[2022, 2023])
        score, _ = _score_liquidity(s, 2023, [2022, 2023])
        assert score == 1

    def test_none_cr_gives_zero(self):
        s = _summary(cr_vals={}, years=[2023])
        score, details = _score_liquidity(s, 2023, [2023])
        assert score == 0
        assert "No current ratio" in details

    def test_details_contains_cr_value(self):
        s = _summary(cr_vals={2023: 1.5}, years=[2023])
        _, details = _score_liquidity(s, 2023, [2023])
        assert "1.50" in details


# =============================================================================
# Profitability scorer
# =============================================================================

class TestProfitabilityScoring:

    def test_severe_drop_gives_minus_2(self):
        # Net margin 20% -> 10%: drop = -10pp > 5pp threshold
        s = _summary(nm_vals={2022: 0.20, 2023: 0.10}, years=[2022, 2023])
        score, details = _score_profitability(s, 2023, [2022, 2023])
        assert score == -2
        assert "severe" in details.lower()

    def test_moderate_drop_gives_minus_1(self):
        # Net margin 20% -> 17%: drop = -3pp, between -5pp and -2pp
        s = _summary(nm_vals={2022: 0.20, 2023: 0.17}, years=[2022, 2023])
        score, _ = _score_profitability(s, 2023, [2022, 2023])
        assert score == -1

    def test_improvement_more_than_2pp_gives_plus_1(self):
        s = _summary(nm_vals={2022: 0.10, 2023: 0.13}, years=[2022, 2023])
        score, _ = _score_profitability(s, 2023, [2022, 2023])
        assert score == 1

    def test_stable_change_less_than_2pp_gives_zero(self):
        s = _summary(nm_vals={2022: 0.15, 2023: 0.16}, years=[2022, 2023])
        score, _ = _score_profitability(s, 2023, [2022, 2023])
        assert score == 0

    def test_two_consecutive_declines_gives_extra_minus_1(self):
        # 2021: 20%, 2022: 18% (decline), 2023: 15% (decline again) => -1 + -1 extra
        s = _summary(
            nm_vals={2021: 0.20, 2022: 0.18, 2023: 0.15},
            years=[2021, 2022, 2023],
        )
        score, details = _score_profitability(s, 2023, [2021, 2022, 2023])
        # -1 for moderate drop + -1 for consecutive = -2
        assert score == -2
        assert "consecutive" in details.lower()

    def test_single_year_gives_zero(self):
        s = _summary(nm_vals={2023: 0.15}, years=[2023])
        score, _ = _score_profitability(s, 2023, [2023])
        assert score == 0

    def test_none_nm_gives_zero(self):
        s = _summary(nm_vals={}, years=[2023])
        score, details = _score_profitability(s, 2023, [2023])
        assert score == 0
        assert "No net margin" in details


# =============================================================================
# Revenue Stability scorer
# =============================================================================

class TestRevenueStabilityScoring:

    def test_revenue_decline_gives_minus_1(self):
        s = _summary(rev_vals={2022: 1000, 2023: 900}, years=[2022, 2023])
        score, details = _score_revenue_stability(s, 2023, [2022, 2023])
        assert score == -1
        assert "declined" in details.lower()

    def test_two_consecutive_declines_gives_minus_2(self):
        s = _summary(
            rev_vals={2021: 1000, 2022: 900, 2023: 800},
            years=[2021, 2022, 2023],
        )
        score, details = _score_revenue_stability(s, 2023, [2021, 2022, 2023])
        assert score == -2
        assert "consecutive" in details.lower()

    def test_strong_growth_gives_plus_1(self):
        # 20% growth > 15% threshold
        s = _summary(rev_vals={2022: 1000, 2023: 1200}, years=[2022, 2023])
        score, details = _score_revenue_stability(s, 2023, [2022, 2023])
        assert score == 1
        assert "strong" in details.lower()

    def test_moderate_growth_gives_zero(self):
        # 10% growth < 15% threshold
        s = _summary(rev_vals={2022: 1000, 2023: 1100}, years=[2022, 2023])
        score, _ = _score_revenue_stability(s, 2023, [2022, 2023])
        assert score == 0

    def test_single_year_gives_zero(self):
        s = _summary(rev_vals={2023: 1000}, years=[2023])
        score, _ = _score_revenue_stability(s, 2023, [2023])
        assert score == 0

    def test_none_revenue_gives_zero(self):
        s = _summary(rev_vals={}, years=[2023])
        score, details = _score_revenue_stability(s, 2023, [2023])
        assert score == 0
        assert "No revenue" in details


# =============================================================================
# Leverage scorer
# =============================================================================

class TestLeverageScoring:

    def test_dte_increase_more_than_20pct_gives_minus_1(self):
        # DTE: 100/500=0.20 -> 130/500=0.26; change = +30%
        s = _summary(
            ld_vals={2022: 100, 2023: 130},
            eq_vals={2022: 500, 2023: 500},
            years=[2022, 2023],
        )
        score, details = _score_leverage(s, 2023, [2022, 2023])
        assert score == -1
        assert "increased" in details.lower()

    def test_dte_decrease_more_than_20pct_gives_plus_1(self):
        # DTE: 200/500=0.40 -> 130/500=0.26; change = -35%
        s = _summary(
            ld_vals={2022: 200, 2023: 130},
            eq_vals={2022: 500, 2023: 500},
            years=[2022, 2023],
        )
        score, details = _score_leverage(s, 2023, [2022, 2023])
        assert score == 1
        assert "decreased" in details.lower()

    def test_small_dte_change_gives_zero(self):
        # DTE: 100/500=0.20 -> 110/500=0.22; change = +10%
        s = _summary(
            ld_vals={2022: 100, 2023: 110},
            eq_vals={2022: 500, 2023: 500},
            years=[2022, 2023],
        )
        score, _ = _score_leverage(s, 2023, [2022, 2023])
        assert score == 0

    def test_non_positive_equity_gives_minus_2(self):
        s = _summary(
            ld_vals={2023: 100},
            eq_vals={2023: 0},
            years=[2023],
        )
        score, details = _score_leverage(s, 2023, [2023])
        assert score == -2
        assert "non-positive" in details.lower()

    def test_no_debt_data_gives_zero(self):
        s = _summary(eq_vals={2023: 500}, years=[2023])
        score, details = _score_leverage(s, 2023, [2023])
        assert score == 0
        assert "No long-term debt" in details

    def test_no_equity_data_gives_zero(self):
        s = _summary(ld_vals={2023: 100}, years=[2023])
        score, details = _score_leverage(s, 2023, [2023])
        assert score == 0
        assert "No equity" in details


# =============================================================================
# analyze_risk — integration
# =============================================================================

class TestAnalyzeRisk:

    def test_returns_expected_keys(self):
        s = _summary(
            cr_vals={2023: 2.0}, nm_vals={2023: 0.15},
            rev_vals={2023: 1000}, eq_vals={2023: 500},
            years=[2023],
        )
        result = analyze_risk(s, [2023])
        assert set(result.keys()) == {"overall_score", "overall_level", "categories"}

    def test_categories_have_expected_shape(self):
        s = _summary(
            cr_vals={2023: 2.0}, nm_vals={2023: 0.15},
            rev_vals={2023: 1000}, eq_vals={2023: 500},
            years=[2023],
        )
        result = analyze_risk(s, [2023])
        assert len(result["categories"]) == 4
        for cat in result["categories"]:
            assert {"name", "score", "severity", "details"} == set(cat.keys())

    def test_empty_years_returns_default(self):
        result = analyze_risk({}, [])
        assert result["overall_score"] == 0
        assert result["overall_level"] == "Low"
        assert result["categories"] == []

    def test_overall_level_elevated_when_all_bad(self):
        # Liquidity: CR 0.8 -> -2 base, big decline -> at least -2
        # Profitability: severe net margin drop -> -2
        # Revenue: two consecutive declines -> -2
        # Leverage: negative equity -> -2
        # Total ≤ -8 → Elevated
        s = _summary(
            cr_vals={2021: 2.0, 2022: 1.5, 2023: 0.8},
            nm_vals={2021: 0.20, 2022: 0.18, 2023: 0.08},
            rev_vals={2021: 1000, 2022: 900, 2023: 800},
            ld_vals={2023: 100},
            eq_vals={2021: 500, 2022: 400, 2023: -50},
            years=[2021, 2022, 2023],
        )
        result = analyze_risk(s, [2021, 2022, 2023])
        assert result["overall_level"] == "Elevated"
        assert result["overall_score"] <= -4

    def test_overall_level_strong_when_all_good(self):
        # CR > 2.5, big improvement → +2 (base 0 + yoy +1 + CR bonus +1)
        # Net margin large improvement → +1
        # Revenue strong growth → +1
        # Leverage: DTE big decrease → +1
        # Total = 5 → Strong
        s = _summary(
            cr_vals={2022: 2.0, 2023: 3.0},
            nm_vals={2022: 0.05, 2023: 0.12},
            rev_vals={2022: 1000, 2023: 1200},
            ld_vals={2022: 200, 2023: 100},
            eq_vals={2022: 500, 2023: 500},
            years=[2022, 2023],
        )
        result = analyze_risk(s, [2022, 2023])
        assert result["overall_level"] == "Strong"
        assert result["overall_score"] >= 3

    def test_category_names_are_correct(self):
        s = _summary(years=[2023])
        result = analyze_risk(s, [2023])
        names = [c["name"] for c in result["categories"]]
        assert names == ["Liquidity", "Profitability", "Revenue Stability", "Leverage"]

    def test_overall_score_is_sum_of_category_scores(self):
        s = _summary(
            cr_vals={2022: 2.0, 2023: 1.5},
            nm_vals={2022: 0.15, 2023: 0.16},
            rev_vals={2022: 1000, 2023: 1100},
            eq_vals={2022: 500, 2023: 500},
            years=[2022, 2023],
        )
        result = analyze_risk(s, [2022, 2023])
        cat_sum = sum(c["score"] for c in result["categories"])
        assert result["overall_score"] == cat_sum


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
