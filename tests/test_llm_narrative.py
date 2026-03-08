"""
tests/test_llm_narrative.py

Tests for ace_research.narrative_llm.

Coverage:
    TestBuildPrompt      — _build_prompt() serializes summary correctly
    TestGenerateLlmSummary — generate_llm_summary() with mocked Anthropic client
    TestFailureHandling  — API errors propagate; fallback tested via generate_narrative
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import pytest

import ace_research.narrative_llm as llm_module
from ace_research.narrative_llm import _build_prompt, generate_llm_summary


# =============================================================================
# Fixtures
# =============================================================================

SAMPLE_SUMMARY = {
    "company": "Acme Corp",
    "years": [2022, 2023],
    "income_statement": {
        "revenue": {
            "values": {2022: 100_000.0, 2023: 120_000.0},
            "yoy_pct": 20.0,
        },
        "operating_income": {
            "values": {2022: 15_000.0, 2023: 18_000.0},
            "yoy_pct": 20.0,
        },
        "net_income": {
            "values": {2022: 10_000.0, 2023: 12_500.0},
            "yoy_pct": 25.0,
        },
    },
    "balance_sheet": {
        "total_assets": {"values": {2022: 200_000.0, 2023: 220_000.0}},
        "total_liabilities": {"values": {2022: 120_000.0, 2023: 130_000.0}},
        "total_equity": {"values": {2022: 80_000.0, 2023: 90_000.0}},
    },
    "quality_metrics": {
        "gross_margin": {"values": {2022: 0.42, 2023: 0.44}},
        "operating_margin": {"values": {2022: 0.15, 2023: 0.15}},
        "net_margin": {"values": {2022: 0.10, 2023: 0.104}},
        "current_ratio": {"values": {2022: 1.8, 2023: 2.1}},
        "piotroski_score": {"values": {2022: 6, 2023: 7}},
        "risk_flags": ["high_leverage"],
    },
    "risk_analysis": {
        "overall_score": 1,
        "overall_level": "Low",
        "categories": [
            {"name": "Liquidity", "score": 1, "severity": "positive", "details": "CR healthy."},
            {"name": "Profitability", "score": 0, "severity": "stable", "details": "Stable."},
        ],
    },
}

YEARS = [2022, 2023]


def _make_response(text: str):
    """Build a minimal mock Anthropic response object."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


# =============================================================================
# TestBuildPrompt
# =============================================================================

class TestBuildPrompt:
    def test_contains_company_name(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "Acme Corp" in prompt

    def test_contains_all_years(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "2022" in prompt
        assert "2023" in prompt

    def test_contains_revenue_values(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        # Revenue 120,000 appears somewhere in the prompt
        assert "120,000" in prompt

    def test_contains_yoy_for_revenue(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "+20.0%" in prompt

    def test_contains_income_statement_header(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "INCOME STATEMENT" in prompt

    def test_contains_balance_sheet_header(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "BALANCE SHEET" in prompt

    def test_contains_financial_quality_header(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "FINANCIAL QUALITY" in prompt

    def test_contains_piotroski_score(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "Piotroski" in prompt

    def test_contains_risk_flags(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "high_leverage" in prompt

    def test_contains_risk_assessment_when_present(self):
        prompt = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert "RISK ASSESSMENT" in prompt
        assert "Low" in prompt

    def test_no_risk_assessment_when_absent(self):
        import copy
        summary = copy.deepcopy(SAMPLE_SUMMARY)
        del summary["risk_analysis"]
        prompt = _build_prompt(summary, YEARS)
        assert "RISK ASSESSMENT" not in prompt

    def test_none_metric_renders_na(self):
        import copy
        summary = copy.deepcopy(SAMPLE_SUMMARY)
        summary["income_statement"]["revenue"]["values"][2023] = None
        prompt = _build_prompt(summary, YEARS)
        assert "N/A" in prompt

    def test_no_risk_flags_renders_none(self):
        import copy
        summary = copy.deepcopy(SAMPLE_SUMMARY)
        summary["quality_metrics"]["risk_flags"] = []
        prompt = _build_prompt(summary, YEARS)
        assert "Risk Flags: None" in prompt

    def test_returns_string(self):
        result = _build_prompt(SAMPLE_SUMMARY, YEARS)
        assert isinstance(result, str)
        assert len(result) > 0


# =============================================================================
# TestGenerateLlmSummary
# =============================================================================

class TestGenerateLlmSummary:
    """Tests for generate_llm_summary() with the Anthropic client mocked."""

    def _make_mock_client(self, response_text: str) -> MagicMock:
        """Return a mock Anthropic client whose messages.create returns response_text."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_response(response_text)
        return mock_client

    def test_returns_string_on_success(self):
        expected = "Acme Corp showed strong revenue growth in 2023."
        mock_client = self._make_mock_client(expected)

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            result = generate_llm_summary(SAMPLE_SUMMARY, YEARS)

        assert isinstance(result, str)
        assert result == expected

    def test_returns_non_empty_string(self):
        mock_client = self._make_mock_client("Revenue grew 20%. Profitability improved.")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            result = generate_llm_summary(SAMPLE_SUMMARY, YEARS)
        assert len(result) > 0

    def test_prompt_is_sent_to_api(self):
        """The metrics text block must appear in the user message sent to the API."""
        mock_client = self._make_mock_client("Summary text.")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            generate_llm_summary(SAMPLE_SUMMARY, YEARS)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "Acme Corp" in user_content
        assert "INCOME STATEMENT" in user_content

    def test_correct_model_is_used(self):
        mock_client = self._make_mock_client("Summary.")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            generate_llm_summary(SAMPLE_SUMMARY, YEARS)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == llm_module._MODEL

    def test_correct_temperature_is_used(self):
        mock_client = self._make_mock_client("Summary.")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            generate_llm_summary(SAMPLE_SUMMARY, YEARS)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == llm_module._TEMPERATURE

    def test_correct_max_tokens_is_used(self):
        mock_client = self._make_mock_client("Summary.")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            generate_llm_summary(SAMPLE_SUMMARY, YEARS)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == llm_module._MAX_TOKENS

    def test_system_prompt_is_included(self):
        mock_client = self._make_mock_client("Summary.")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            generate_llm_summary(SAMPLE_SUMMARY, YEARS)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" in call_kwargs
        assert len(call_kwargs["system"]) > 0

    def test_strips_leading_trailing_whitespace(self):
        mock_client = self._make_mock_client("  Revenue grew.  ")
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            result = generate_llm_summary(SAMPLE_SUMMARY, YEARS)
        assert result == "Revenue grew."


# =============================================================================
# TestFailureHandling
# =============================================================================

class TestFailureHandling:
    """API failures must propagate so the caller can fall back."""

    def test_api_error_is_raised(self):
        """generate_llm_summary must NOT swallow API exceptions."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIConnectionError(
            request=MagicMock()
        )
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("ace_research.narrative_llm.anthropic.Anthropic", return_value=mock_client),
        ):
            with pytest.raises(Exception):
                generate_llm_summary(SAMPLE_SUMMARY, YEARS)

    def test_missing_api_key_raises_key_error(self):
        """KeyError propagates when ANTHROPIC_API_KEY is absent."""
        env_without_key = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            with pytest.raises(KeyError):
                generate_llm_summary(SAMPLE_SUMMARY, YEARS)

    def test_generate_narrative_llm_mode_falls_back_on_failure(self):
        """
        generate_narrative(mode='llm') must return a non-empty deterministic string
        when generate_llm_summary raises any exception.
        """
        import copy
        from ace_research.report_narrative import generate_narrative

        summary = copy.deepcopy(SAMPLE_SUMMARY)

        # generate_narrative does a lazy `from ace_research.narrative_llm import
        # generate_llm_summary` inside the function body, so patching the module
        # attribute is the correct approach.
        with patch(
            "ace_research.narrative_llm.generate_llm_summary",
            side_effect=RuntimeError("API unavailable"),
        ):
            result = generate_narrative(summary, mode="llm")

        assert isinstance(result, str)
        assert len(result) > 0
        assert "Acme Corp" in result

    def test_generate_narrative_unknown_mode_raises(self):
        """generate_narrative raises NotImplementedError for unsupported modes."""
        import copy
        from ace_research.report_narrative import generate_narrative

        summary = copy.deepcopy(SAMPLE_SUMMARY)
        with pytest.raises(NotImplementedError):
            generate_narrative(summary, mode="gpt")
