"""
tests/test_orchestration.py

Unit tests for ace_research/orchestration.py.

All DB calls, file I/O, and network operations are mocked.
No database fixture required.
"""

import pytest
from unittest.mock import patch, MagicMock, call

from ace_research.orchestration import ensure_company_years_ready


# =============================================================================
# Helpers
# =============================================================================

def _patch_all(revenue=None, local_file=None, downloaded=None):
    """Return a context-manager stack that patches every external call."""
    return (
        patch("ace_research.orchestration.get_canonical_financial_fact",
              return_value=revenue),
        patch("ace_research.orchestration._find_local_filing",
              return_value=local_file),
        patch("ace_research.orchestration.download_10k",
              return_value=downloaded),
        patch("ace_research.orchestration.ingest_local_xbrl_file"),
        patch("ace_research.orchestration.backfill_canonical_from_raw"),
    )


# =============================================================================
# Tests: canonical data already present
# =============================================================================

class TestSkipsWhenDataPresent:

    def test_no_download_when_revenue_present(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=1000.0) as mock_gcf, \
             patch("ace_research.orchestration.download_10k") as mock_dl, \
             patch("ace_research.orchestration.ingest_local_xbrl_file") as mock_ingest:
            ensure_company_years_ready("Microsoft", [2022])
        mock_dl.assert_not_called()
        mock_ingest.assert_not_called()

    def test_no_ingest_when_revenue_present(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=500.0), \
             patch("ace_research.orchestration.backfill_canonical_from_raw") as mock_bf:
            ensure_company_years_ready("Google", [2022, 2023])
        mock_bf.assert_not_called()

    def test_multiple_years_all_skip_when_all_present(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=100.0), \
             patch("ace_research.orchestration.download_10k") as mock_dl:
            ensure_company_years_ready("Microsoft", [2020, 2021, 2022])
        mock_dl.assert_not_called()


# =============================================================================
# Tests: local file found — use it without downloading
# =============================================================================

class TestUsesLocalFileWhenAvailable:

    def test_ingest_called_with_local_file(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing",
                   return_value="/data/sec/goog-20221231.htm"), \
             patch("ace_research.orchestration.download_10k") as mock_dl, \
             patch("ace_research.orchestration.ingest_local_xbrl_file") as mock_ingest, \
             patch("ace_research.orchestration.backfill_canonical_from_raw"):
            ensure_company_years_ready("Google", [2022])

        mock_dl.assert_not_called()
        mock_ingest.assert_called_once_with(
            file_path="/data/sec/goog-20221231.htm", company="Google"
        )

    def test_backfill_called_after_ingest(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing",
                   return_value="/data/sec/goog-20221231.htm"), \
             patch("ace_research.orchestration.download_10k"), \
             patch("ace_research.orchestration.ingest_local_xbrl_file"), \
             patch("ace_research.orchestration.backfill_canonical_from_raw") as mock_bf:
            ensure_company_years_ready("Google", [2022])

        mock_bf.assert_called_once_with(["Google"])


# =============================================================================
# Tests: local file absent — download from SEC EDGAR
# =============================================================================

class TestDownloadsWhenNoLocalFile:

    def test_download_called_for_known_company(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing", return_value=None), \
             patch("ace_research.orchestration.download_10k",
                   return_value="/data/sec/goog-2023-02-03.htm") as mock_dl, \
             patch("ace_research.orchestration.ingest_local_xbrl_file"), \
             patch("ace_research.orchestration.backfill_canonical_from_raw"):
            ensure_company_years_ready("Google", [2022])

        mock_dl.assert_called_once_with("Google", 2022)

    def test_ingest_and_backfill_called_after_download(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing", return_value=None), \
             patch("ace_research.orchestration.download_10k",
                   return_value="/data/sec/goog-2023-02-03.htm"), \
             patch("ace_research.orchestration.ingest_local_xbrl_file") as mock_ingest, \
             patch("ace_research.orchestration.backfill_canonical_from_raw") as mock_bf:
            ensure_company_years_ready("Google", [2022])

        mock_ingest.assert_called_once_with(
            file_path="/data/sec/goog-2023-02-03.htm", company="Google"
        )
        mock_bf.assert_called_once_with(["Google"])

    def test_skip_when_download_returns_none(self):
        """If SEC EDGAR has no matching filing, ingest must not be called."""
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing", return_value=None), \
             patch("ace_research.orchestration.download_10k", return_value=None), \
             patch("ace_research.orchestration.ingest_local_xbrl_file") as mock_ingest:
            ensure_company_years_ready("Google", [1990])

        mock_ingest.assert_not_called()


# =============================================================================
# Tests: unknown company
# =============================================================================

class TestUnknownCompany:

    def test_skips_unknown_company_silently(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing", return_value=None), \
             patch("ace_research.orchestration.download_10k") as mock_dl, \
             patch("ace_research.orchestration.ingest_local_xbrl_file") as mock_ingest:
            ensure_company_years_ready("UnknownCo", [2022])

        mock_dl.assert_not_called()
        mock_ingest.assert_not_called()

    def test_no_exception_for_unknown_company(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   return_value=None), \
             patch("ace_research.orchestration._find_local_filing", return_value=None), \
             patch("ace_research.orchestration.download_10k"), \
             patch("ace_research.orchestration.ingest_local_xbrl_file"):
            # Must not raise
            ensure_company_years_ready("MysteryInc", [2022, 2023])


# =============================================================================
# Tests: multi-year iteration
# =============================================================================

class TestMultipleYears:

    def test_processes_each_year_independently(self):
        """Mixed years: 2022 present, 2023 missing → only 2023 triggers ingest."""
        def fake_gcf(metric, year, company):
            return 100.0 if year == 2022 else None

        with patch("ace_research.orchestration.get_canonical_financial_fact",
                   side_effect=fake_gcf), \
             patch("ace_research.orchestration._find_local_filing",
                   return_value="/data/sec/msft-20230630.htm"), \
             patch("ace_research.orchestration.download_10k"), \
             patch("ace_research.orchestration.ingest_local_xbrl_file") as mock_ingest, \
             patch("ace_research.orchestration.backfill_canonical_from_raw") as mock_bf:
            ensure_company_years_ready("Microsoft", [2022, 2023])

        # ingest called exactly once (only for 2023)
        mock_ingest.assert_called_once_with(
            file_path="/data/sec/msft-20230630.htm", company="Microsoft"
        )
        mock_bf.assert_called_once_with(["Microsoft"])

    def test_empty_years_list_does_nothing(self):
        with patch("ace_research.orchestration.get_canonical_financial_fact") as mock_gcf, \
             patch("ace_research.orchestration.download_10k") as mock_dl:
            ensure_company_years_ready("Google", [])

        mock_gcf.assert_not_called()
        mock_dl.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
