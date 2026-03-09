"""
tests/test_charts.py

Tests for ace_research/charts.py.

Coverage:
    TestGenerateCharts     — generate_charts() happy path
    TestChartWithNoneData  — graceful handling of None/partial values
    TestChartUnavailable   — ImportError when matplotlib is absent
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

SAMPLE_SUMMARY = {
    "company": "ChartCo",
    "years": [2021, 2022, 2023],
    "income_statement": {
        "revenue": {
            "values": {2021: 168_000.0, 2022: 198_000.0, 2023: 211_000.0},
            "yoy_pct": 6.6,
        },
        "operating_income": {"values": {2021: 70_000.0, 2022: 83_000.0, 2023: 88_000.0}, "yoy_pct": 6.0},
        "net_income":       {"values": {2021: 61_000.0, 2022: 72_000.0, 2023: 72_000.0}, "yoy_pct": 0.0},
    },
    "balance_sheet": {
        "total_assets":      {"values": {2021: 300_000.0, 2022: 360_000.0, 2023: 411_000.0}},
        "total_liabilities": {"values": {2021: 190_000.0, 2022: 210_000.0, 2023: 205_000.0}},
        "total_equity":      {"values": {2021: 110_000.0, 2022: 150_000.0, 2023: 206_000.0}},
    },
    "quality_metrics": {
        "gross_margin":      {"values": {2021: 0.68, 2022: 0.69, 2023: 0.69}},
        "operating_margin":  {"values": {2021: 0.42, 2022: 0.42, 2023: 0.42}},
        "net_margin":        {"values": {2021: 0.367, 2022: 0.363, 2023: 0.341}},
        "current_ratio":     {"values": {2021: 2.08, 2022: 1.78, 2023: 1.77}},
        "piotroski_score":   {"values": {2021: 6, 2022: 6, 2023: 6}},
        "risk_flags":        [],
        "asset_turnover":    {"values": {2021: 0.56, 2022: 0.55, 2023: 0.51}},
        "return_on_assets":  {"values": {2021: 0.20, 2022: 0.20, 2023: 0.18}},
        "return_on_equity":  {"values": {2021: 0.55, 2022: 0.48, 2023: 0.35}},
        "debt_ratio":        {"values": {2021: 0.63, 2022: 0.58, 2023: 0.50}},
        "quick_ratio":       {"values": {2021: 2.08, 2022: 1.78, 2023: 1.77}},
    },
}

YEARS = [2021, 2022, 2023]


# =============================================================================
# TestGenerateCharts
# =============================================================================

class TestGenerateCharts:

    def test_returns_list_of_four_paths(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(SAMPLE_SUMMARY, YEARS)
        try:
            assert isinstance(paths, list)
            assert len(paths) == 4
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_all_files_exist(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(SAMPLE_SUMMARY, YEARS)
        try:
            for p in paths:
                assert os.path.isfile(p), f"Chart file not found: {p}"
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_all_files_are_png(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(SAMPLE_SUMMARY, YEARS)
        try:
            for p in paths:
                assert p.endswith(".png"), f"Expected .png extension: {p}"
                with open(p, "rb") as f:
                    header = f.read(8)
                assert header[:8] == b"\x89PNG\r\n\x1a\n", f"Not a valid PNG: {p}"
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_files_have_non_zero_size(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(SAMPLE_SUMMARY, YEARS)
        try:
            for p in paths:
                assert os.path.getsize(p) > 0, f"Empty chart file: {p}"
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_paths_are_absolute(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(SAMPLE_SUMMARY, YEARS)
        try:
            for p in paths:
                assert os.path.isabs(p), f"Expected absolute path: {p}"
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_each_chart_is_a_distinct_file(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(SAMPLE_SUMMARY, YEARS)
        try:
            assert len(set(paths)) == 4
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass


# =============================================================================
# TestChartWithNoneData
# =============================================================================

class TestChartWithNoneData:
    """Charts must not crash when metric values are None or partially missing."""

    def _sparse_summary(self):
        import copy
        s = copy.deepcopy(SAMPLE_SUMMARY)
        # Remove all revenue values so the revenue chart has no data
        s["income_statement"]["revenue"]["values"] = {2021: None, 2022: None, 2023: None}
        # Partial data for ROE
        s["quality_metrics"]["return_on_equity"]["values"][2022] = None
        return s

    def test_none_values_do_not_raise(self):
        from ace_research.charts import generate_charts
        paths = generate_charts(self._sparse_summary(), YEARS)
        try:
            assert len(paths) == 4
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_all_none_still_produces_file(self):
        """An empty chart (all None values) should still write a valid PNG."""
        from ace_research.charts import generate_charts
        paths = generate_charts(self._sparse_summary(), YEARS)
        try:
            for p in paths:
                assert os.path.isfile(p)
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_missing_quality_key_does_not_raise(self):
        """If a metric key is absent from quality_metrics, chart still renders."""
        import copy
        from ace_research.charts import generate_charts
        s = copy.deepcopy(SAMPLE_SUMMARY)
        del s["quality_metrics"]["return_on_equity"]
        del s["quality_metrics"]["debt_ratio"]
        paths = generate_charts(s, YEARS)
        try:
            assert len(paths) == 4
        finally:
            for p in paths:
                try:
                    os.unlink(p)
                except Exception:
                    pass


# =============================================================================
# TestChartUnavailable
# =============================================================================

class TestChartUnavailable:

    def test_raises_import_error_when_matplotlib_unavailable(self):
        from ace_research import charts as charts_module
        with patch.object(charts_module, "_MATPLOTLIB_AVAILABLE", False):
            with pytest.raises(ImportError, match="matplotlib"):
                charts_module.generate_charts(SAMPLE_SUMMARY, YEARS)
