import os
import requests
from arelle import Cntlr

from ace_research.xbrl.mappings import XBRL_METRIC_MAP  # not used yet, but kept for next steps


# ----------------------------
# Configuration
# ----------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "sec")

SEC_HEADERS = {
    "User-Agent": "Mohit Mohanraj mohitmohanraj05@gmail.com"
}


# ----------------------------
# SEC helpers
# ----------------------------

def fetch_company_filings(cik: str) -> dict:
    """
    Fetch company submission metadata from SEC.
    """
    cik = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=SEC_HEADERS)
    resp.raise_for_status()
    return resp.json()


def find_10k_html_urls(cik: str, years: list[int]) -> list[str]:
    """
    Locate inline XBRL (HTML) 10-K filing URLs for given years.
    """
    data = fetch_company_filings(cik)
    filings = data["filings"]["recent"]

    urls = []

    for i, form in enumerate(filings["form"]):
        if form != "10-K":
            continue

        filing_year = int(filings["filingDate"][i][:4])
        if filing_year not in years:
            continue

        accession = filings["accessionNumber"][i].replace("-", "")
        primary_doc = filings["primaryDocument"][i]

        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession}/{primary_doc}"
        )
        urls.append(url)

    return urls


# ----------------------------
# Main ingestion entrypoint
# ----------------------------

def ingest_company_xbrl(company: str, cik: str, years: list[int]) -> None:

    print(f"\nLocating 10-K filings for {company} ({cik})...")
    urls = find_10k_html_urls(cik, years)

    if not urls:
        print("No 10-K filings found for requested years.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)

    for url in urls:
        print(f"\nDownloading inline XBRL filing:")
        print(url)

        filename = url.split("/")[-1]
        local_path = os.path.join(DATA_DIR, filename)

        resp = requests.get(url, headers=SEC_HEADERS)
        resp.raise_for_status()

        with open(local_path, "wb") as f:
            f.write(resp.content)

        print(f"Saved to: {local_path}")

        # ---- Verify with Arelle (NO parsing yet) ----
        cntlr = Cntlr.Cntlr(logFileName=None)
        model_xbrl = cntlr.modelManager.load(local_path)

        if model_xbrl is None:
            print("Arelle failed to load XBRL instance.")
        else:
            print("Arelle successfully loaded inline XBRL.")
            print(f"   Facts detected: {len(model_xbrl.facts)}")

        # Only validate one filing for now
        break


print("ingest.py loaded")