"""
tests/test_sec_fetch.py

Unit tests for ace_research/sec/fetch.py.

All HTTP calls and filesystem writes are mocked — no network access required.
"""

import pytest
from unittest.mock import patch, MagicMock

import ace_research.sec.fetch as fetch_module
from ace_research.sec.fetch import (
    get_10k_metadata,
    download_10k,
    COMPANY_TO_TICKER,
    COMPANY_TO_CIK,
)


# =============================================================================
# Shared mock data
# =============================================================================

_MOCK_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form":            ["10-K",                  "10-Q",                  "10-K"],
            "accessionNumber": ["0001652044-23-000016",  "0001652044-23-000020",  "0001652044-22-000009"],
            "filingDate":      ["2023-02-03",            "2023-05-01",            "2022-02-04"],
            "reportDate":      ["2022-12-31",            "2023-03-31",            "2021-12-31"],
            "primaryDocument": ["goog-20221231.htm",     "goog-20230331.htm",     "goog-20211231.htm"],
        }
    }
}


def _mock_get(json_payload=None, content=b"<html>filing</html>"):
    resp = MagicMock()
    resp.json.return_value = json_payload or _MOCK_SUBMISSIONS
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


# =============================================================================
# Company registry
# =============================================================================

class TestCompanyRegistry:

    def test_microsoft_ticker(self):
        assert COMPANY_TO_TICKER.get("Microsoft") == "msft"

    def test_google_ticker(self):
        assert COMPANY_TO_TICKER.get("Google") == "goog"

    def test_microsoft_cik(self):
        assert "Microsoft" in COMPANY_TO_CIK
        assert COMPANY_TO_CIK["Microsoft"].isdigit()

    def test_google_cik(self):
        assert "Google" in COMPANY_TO_CIK
        assert COMPANY_TO_CIK["Google"].isdigit()


# =============================================================================
# get_10k_metadata
# =============================================================================

class TestGet10kMetadata:

    def test_returns_dict_for_known_year(self):
        with patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()):
            result = get_10k_metadata("Google", 2022)
        assert result is not None
        assert result["accession"] == "0001652044-23-000016"
        assert result["primary_document"] == "goog-20221231.htm"
        assert result["filing_date"] == "2023-02-03"

    def test_returns_dict_for_prior_year(self):
        with patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()):
            result = get_10k_metadata("Google", 2021)
        assert result is not None
        assert result["accession"] == "0001652044-22-000009"

    def test_returns_none_for_unmatched_year(self):
        with patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()):
            result = get_10k_metadata("Google", 2019)
        assert result is None

    def test_raises_value_error_for_unknown_company(self):
        with pytest.raises(ValueError, match="Unknown company"):
            get_10k_metadata("UnknownCo", 2022)

    def test_skips_non_10k_forms(self):
        """A 10-Q filing whose reportDate matches must NOT be returned."""
        submissions = {
            "filings": {
                "recent": {
                    "form":            ["10-Q"],
                    "accessionNumber": ["0001652044-23-000020"],
                    "filingDate":      ["2023-05-01"],
                    "reportDate":      ["2022-12-31"],
                    "primaryDocument": ["goog-20221231.htm"],
                }
            }
        }
        with patch("ace_research.sec.fetch.requests.get", return_value=_mock_get(submissions)):
            result = get_10k_metadata("Google", 2022)
        assert result is None

    def test_user_agent_header_is_sent(self):
        with patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()) as mock_get:
            get_10k_metadata("Google", 2022)
        _, kwargs = mock_get.call_args
        assert "User-Agent" in kwargs.get("headers", {})

    def test_raises_http_error_on_bad_response(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("HTTP 500")
        with patch("ace_research.sec.fetch.requests.get", return_value=resp):
            with pytest.raises(Exception, match="HTTP 500"):
                get_10k_metadata("Google", 2022)

    def test_empty_filings_returns_none(self):
        empty = {"filings": {"recent": {}}}
        with patch("ace_research.sec.fetch.requests.get", return_value=_mock_get(empty)):
            result = get_10k_metadata("Google", 2022)
        assert result is None


# =============================================================================
# download_10k
# =============================================================================

class TestDownload10k:

    def test_returns_none_when_no_metadata(self):
        with patch("ace_research.sec.fetch.get_10k_metadata", return_value=None):
            result = download_10k("Google", 2019)
        assert result is None

    def test_raises_for_unknown_company(self):
        with pytest.raises(ValueError, match="Unknown company"):
            download_10k("UnknownCo", 2022)

    def test_saves_file_and_returns_path(self, tmp_path):
        meta = {
            "accession":        "0001652044-23-000016",
            "primary_document": "goog-20221231.htm",
            "filing_date":      "2023-02-03",
        }
        with patch.object(fetch_module, "_DATA_DIR", tmp_path), \
             patch("ace_research.sec.fetch.get_10k_metadata", return_value=meta), \
             patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()), \
             patch("ace_research.sec.fetch.time.sleep"):
            result = download_10k("Google", 2022)

        expected = str(tmp_path / "goog-2023-02-03.htm")
        assert result == expected
        assert (tmp_path / "goog-2023-02-03.htm").exists()

    def test_file_content_written_correctly(self, tmp_path):
        meta = {
            "accession":        "0001652044-23-000016",
            "primary_document": "goog-20221231.htm",
            "filing_date":      "2023-02-03",
        }
        payload = b"<html><body>10-K filing content</body></html>"
        with patch.object(fetch_module, "_DATA_DIR", tmp_path), \
             patch("ace_research.sec.fetch.get_10k_metadata", return_value=meta), \
             patch("ace_research.sec.fetch.requests.get", return_value=_mock_get(content=payload)), \
             patch("ace_research.sec.fetch.time.sleep"):
            download_10k("Google", 2022)

        assert (tmp_path / "goog-2023-02-03.htm").read_bytes() == payload

    def test_respects_rate_limit(self, tmp_path):
        meta = {
            "accession":        "0001652044-23-000016",
            "primary_document": "goog-20221231.htm",
            "filing_date":      "2023-02-03",
        }
        with patch.object(fetch_module, "_DATA_DIR", tmp_path), \
             patch("ace_research.sec.fetch.get_10k_metadata", return_value=meta), \
             patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()), \
             patch("ace_research.sec.fetch.time.sleep") as mock_sleep:
            download_10k("Google", 2022)

        mock_sleep.assert_called_once_with(0.2)

    def test_creates_data_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "new_sec_dir"
        assert not new_dir.exists()
        meta = {
            "accession":        "0001652044-23-000016",
            "primary_document": "goog-20221231.htm",
            "filing_date":      "2023-02-03",
        }
        with patch.object(fetch_module, "_DATA_DIR", new_dir), \
             patch("ace_research.sec.fetch.get_10k_metadata", return_value=meta), \
             patch("ace_research.sec.fetch.requests.get", return_value=_mock_get()), \
             patch("ace_research.sec.fetch.time.sleep"):
            download_10k("Google", 2022)

        assert new_dir.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
