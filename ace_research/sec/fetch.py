"""
ace_research/sec/fetch.py

SEC EDGAR 10-K fetch utilities.

Responsibilities:
    - Map company name to CIK and ticker
    - Fetch 10-K filing metadata from the SEC EDGAR submissions API
    - Download the primary filing document for a given company and fiscal year
    - Save locally to data/sec/ with standardised naming

No ingestion logic. No database calls.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import requests


# =============================================================================
# Company registry
# =============================================================================

COMPANY_TO_TICKER: dict[str, str] = {
    "Microsoft": "msft",
    "Google":    "goog",
    "Apple":     "aapl",
    "Nvidia":    "nvda",
    "Amazon":    "amzn",
    "Meta":      "meta",
    "Tesla":     "tsla",
}

COMPANY_TO_CIK: dict[str, str] = {
    "Microsoft": "0000789019",
    "Google":    "0001652044",
    "Apple":     "0000320193",
    "Nvidia":    "0001045810",
    "Amazon":    "0001018724",
    "Meta":      "0001326801",
    "Tesla":     "0001318605",
}


# =============================================================================
# Internal constants
# =============================================================================

# SEC EDGAR requires a descriptive User-Agent; update email for production use.
_USER_AGENT = "ACE-Research-Project your_email@example.com"

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_URL = (
    "https://www.sec.gov/Archives/edgar/data"
    "/{cik_int}/{accession_clean}/{primary_doc}"
)

# Polite crawl delay required by SEC EDGAR fair-use policy
_RATE_LIMIT_SECONDS = 0.2

# Resolved at import time relative to this file:
#   ace_research/sec/fetch.py  → ../../..  → project root
_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "sec"


# =============================================================================
# Private helpers
# =============================================================================

def _cik(company: str) -> str:
    """Return zero-padded CIK string, or raise ValueError for unknown company."""
    cik = COMPANY_TO_CIK.get(company)
    if cik is None:
        raise ValueError(
            f"Unknown company '{company}'. "
            "Add to COMPANY_TO_CIK in ace_research/sec/fetch.py."
        )
    return cik


def _ticker(company: str) -> str:
    """Return lowercase ticker, or raise ValueError for unknown company."""
    ticker = COMPANY_TO_TICKER.get(company)
    if ticker is None:
        raise ValueError(
            f"Unknown company '{company}'. "
            "Add to COMPANY_TO_TICKER in ace_research/sec/fetch.py."
        )
    return ticker


# =============================================================================
# Public API
# =============================================================================

def get_10k_metadata(company: str, year: int) -> Optional[dict]:
    """
    Fetch 10-K filing metadata for the fiscal year whose period ended in ``year``.

    Calls the SEC EDGAR submissions JSON endpoint and searches for the first
    annual 10-K filing whose ``reportDate`` falls in the requested year.

    Returns:
        {
            "accession":        "0001652044-23-000016",
            "primary_document": "goog-20221231.htm",
            "filing_date":      "2023-02-03",
        }
        or None if no matching 10-K is found.

    Raises:
        ValueError:              Unknown company.
        requests.HTTPError:      Non-2xx response from SEC EDGAR.
    """
    cik = _cik(company)
    url = _SUBMISSIONS_URL.format(cik=cik)

    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    resp.raise_for_status()

    recent = resp.json().get("filings", {}).get("recent", {})

    forms        = recent.get("form", [])
    accessions   = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    for i, form in enumerate(forms):
        if form != "10-K":
            continue

        report_date = report_dates[i] if i < len(report_dates) else ""
        if not report_date:
            continue

        # Match fiscal year by the year in which the period ended
        if int(report_date[:4]) != year:
            continue

        return {
            "accession":        accessions[i]   if i < len(accessions)   else "",
            "primary_document": primary_docs[i] if i < len(primary_docs) else "",
            "filing_date":      filing_dates[i] if i < len(filing_dates) else "",
        }

    return None


def download_10k(company: str, year: int) -> Optional[str]:
    """
    Download the 10-K primary document for ``company``'s fiscal year ``year``.

    Steps:
        1. Fetch filing metadata via get_10k_metadata().
        2. Construct the SEC EDGAR archives URL.
        3. Apply the polite crawl delay.
        4. Save the response to data/sec/{ticker}-{filing_date}.htm.

    Returns:
        Absolute local file path, or None when no matching 10-K exists.

    Raises:
        ValueError:              Unknown company.
        requests.HTTPError:      Non-2xx response from SEC EDGAR.
    """
    meta = get_10k_metadata(company, year)
    if meta is None:
        return None

    cik_str      = _cik(company)
    tick         = _ticker(company)
    accession    = meta["accession"]
    primary_doc  = meta["primary_document"]
    filing_date  = meta["filing_date"]

    # SEC archives path uses integer CIK and dashes-free accession number
    cik_int          = int(cik_str)
    accession_clean  = accession.replace("-", "")

    url = _ARCHIVES_URL.format(
        cik_int=cik_int,
        accession_clean=accession_clean,
        primary_doc=primary_doc,
    )

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = _DATA_DIR / f"{tick}-{filing_date}.htm"

    # Respect SEC fair-use rate limit before every download
    time.sleep(_RATE_LIMIT_SECONDS)

    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=60)
    resp.raise_for_status()

    file_path.write_bytes(resp.content)
    return str(file_path)
