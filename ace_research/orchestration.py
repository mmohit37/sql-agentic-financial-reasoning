"""
ace_research/orchestration.py

Orchestration: ensure canonical data is available before report generation.

ensure_company_years_ready(company, years)

    For each requested year, checks whether canonical revenue data already
    exists.  If it does not:

        1. Look for an existing local filing in data/sec/
           (matches {ticker}-{year}*.htm)
        2. If none found → download via SEC EDGAR (download_10k)
        3. Ingest via ingest_local_xbrl_file()
        4. Backfill canonical via backfill_canonical_from_raw([company])

No return value.  No printing.  No DB schema changes.
Companies not in the COMPANY_TO_TICKER registry are silently skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ace_research.db import get_canonical_financial_fact
from ace_research.xbrl.ingest import ingest_local_xbrl_file
from ace_research.xbrl.backfill import backfill_canonical_from_raw
from ace_research.sec.fetch import download_10k, COMPANY_TO_TICKER


# data/sec/ relative to project root  (ace_research/../data/sec)
_DATA_DIR = Path(__file__).parent.parent / "data" / "sec"


# =============================================================================
# Private helpers
# =============================================================================

def _find_local_filing(company: str, year: int) -> Optional[str]:
    """
    Scan data/sec/ for an existing filing for this company and fiscal year.

    Matches files whose name starts with ``{ticker}-{year}`` and ends in
    ``.htm`` or ``.html``.

    Returns the file path string if found, else None.
    """
    ticker = COMPANY_TO_TICKER.get(company)
    if ticker is None or not _DATA_DIR.exists():
        return None

    prefix = f"{ticker}-{year}"
    for f in _DATA_DIR.iterdir():
        if f.name.startswith(prefix) and f.suffix in {".htm", ".html"}:
            return str(f)
    return None


# =============================================================================
# Public API
# =============================================================================

def ensure_company_years_ready(company: str, years: list[int]) -> None:
    """
    Guarantee canonical financial data is present for every requested year.

    Algorithm (per year):
        1. get_canonical_financial_fact("revenue", year, company) → if not None,
           data already ingested — skip.
        2. _find_local_filing() → use existing file if present.
        3. Otherwise: download via SEC EDGAR (requires company in registry).
           If company is unknown or download returns None → skip silently.
        4. ingest_local_xbrl_file(file_path, company)
        5. backfill_canonical_from_raw([company])

    Side effects:
        - May write a file to data/sec/
        - May insert rows into financial_facts and raw_xbrl_facts
    """
    for year in years:
        # Step 1: canonical coverage check
        if get_canonical_financial_fact("revenue", year, company) is not None:
            continue  # already present

        # Step 2: look for an existing local filing
        file_path = _find_local_filing(company, year)

        # Step 3: download if not found locally
        if file_path is None:
            if company not in COMPANY_TO_TICKER:
                continue  # unknown company — cannot auto-fetch
            file_path = download_10k(company, year)
            if file_path is None:
                continue  # no matching 10-K on SEC EDGAR

        # Steps 4 & 5: ingest then backfill canonical
        ingest_local_xbrl_file(file_path=file_path, company=company)
        backfill_canonical_from_raw([company])
