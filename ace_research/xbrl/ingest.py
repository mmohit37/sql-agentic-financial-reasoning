import os
import requests
from arelle import Cntlr

from ace_research.xbrl.mappings import XBRL_METRIC_MAP
from ace_research.db import insert_financial_fact
from collections import Counter
from datetime import timedelta
from pathlib import Path


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

            concept_counter = Counter()

            for fact in model_xbrl.facts:
                try:
                    concept_counter[fact.qname.localName] += 1
                except Exception:
                    continue
            
            DEBUG_CONCEPTS = False

            if DEBUG_CONCEPTS:
                print("\nTop 30 concepts in this filing:")
                for name, count in concept_counter.most_common(30):
                    print(f"{name}: {count}")

            facts = model_xbrl.facts

            inserted = 0
            skipped = 0
            canonical_facts = {}

            for fact in facts:
                try:
                    if fact.isNil:
                        skipped += 1
                        continue

                    concept = fact.qname.localName

                    if concept not in XBRL_METRIC_MAP:
                        skipped += 1
                        continue
                    
                    metric = XBRL_METRIC_MAP[concept]

                    if fact.value is None:
                        skipped += 1
                        continue

                    if fact.unit is None and not isinstance(fact.value, (int, float, str)):
                        skipped += 1
                        continue

                    try:
                        value = float(fact.value)
                    except (TypeError, ValueError):
                        skipped += 1
                        continue

                    ctx = model_xbrl.contexts.get(fact.contextID)
                    if ctx is None:
                        skipped += 1
                        continue

                    # Require full fiscal year duration
                    if not is_full_year_context(ctx):
                        skipped += 1
                        continue

                    # Require consolidated context
                    if not is_consolidated_context(ctx):
                        skipped += 1
                        continue

                    year = ctx.endDatetime.year

                    if year is None:
                        skipped += 1
                        continue

                    if years and year not in years:
                        skipped += 1
                        continue

                    print(
                        f"ACCEPTED | {company} | {year} | {metric} | {value}"
                    )

                    key = (company, year, metric)

                    if key not in canonical_facts:
                        canonical_facts[key] = value
                    else:
                    # Keep the strongest signal (simple + safe)
                        canonical_facts[key] = max(
                            canonical_facts[key],
                            value,
                            key=lambda v: abs(v)
                        )

                except Exception:
                    skipped += 1
                    continue
            
            for (company, year, metric), value in canonical_facts.items():
                insert_financial_fact(
                    company=company,
                    year=year,
                    metric=metric,
                    value=value
                )

                inserted += 1

            print(f"Inserted {inserted} facts, skipped {skipped}")

        # Only validate one filing for now
        break

def ingest_local_xbrl_file(
    file_path: str,
    company: str,
    years: list[int] | None = None
) -> None:
    """
    Ingest a locally uploaded XBRL / iXBRL file.
    Supports .xml, .xbrl, .htm, .html
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"XBRL file not found: {file_path}")

    if path.suffix.lower() not in {".xml", ".xbrl", ".htm", ".html"}:
        raise ValueError("Unsupported file type for XBRL ingestion")

    print(f"\nIngesting local XBRL file:")
    print(f"  File: {path}")
    print(f"  Company: {company}")

    cntlr = Cntlr.Cntlr(logFileName=None)
    model_xbrl = cntlr.modelManager.load(str(path))

    if model_xbrl is None:
        print("Arelle failed to load XBRL.")
        return

    print(f"Arelle loaded XBRL")
    print(f"   Facts detected: {len(model_xbrl.facts)}")

    inserted = 0
    skipped = 0

    for fact in model_xbrl.facts:
        try:
            if fact.isNil:
                skipped += 1
                continue

            concept = fact.qname.localName
            if concept not in XBRL_METRIC_MAP:
                skipped += 1
                continue

            metric = XBRL_METRIC_MAP[concept]

            try:
                value = float(fact.value)
            except (TypeError, ValueError):
                skipped += 1
                continue

            ctx = model_xbrl.contexts.get(fact.contextID)
            if ctx is None:
                skipped += 1
                continue

            # Determine year
            if ctx.endDatetime:
                year = ctx.endDatetime.year
            elif ctx.instantDatetime:
                year = ctx.instantDatetime.year
            else:
                skipped += 1
                continue

            if years and year not in years:
                skipped += 1
                continue

            insert_financial_fact(
                company=company,
                year=year,
                metric=metric,
                value=value
            )

            inserted += 1

        except Exception:
            skipped += 1
            continue

    print(f"Inserted {inserted} facts, skipped {skipped}")


def is_full_year_context(ctx) -> bool:
    """
    Accept only duration contexts that span ~1 fiscal year.
    """
    if ctx is None:
        return False

    if ctx.startDatetime is None or ctx.endDatetime is None:
        return False

    duration = ctx.endDatetime - ctx.startDatetime

    # Accept ~1 year (allow filing variance)
    return timedelta(days=330) <= duration <= timedelta(days=400)

def is_consolidated_context(ctx) -> bool:
    """
    Reject segment-specific facts.
    """
    if ctx is None:
        return False

    # Arelle stores dimensions here
    return not ctx.qnameDims