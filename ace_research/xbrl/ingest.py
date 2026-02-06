import os
import requests
import json
import hashlib
from arelle import Cntlr

from ace_research.xbrl.mappings import XBRL_METRIC_MAP
from ace_research.db import insert_financial_fact, insert_raw_xbrl_fact
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

            # PHASE 1: Insert ALL numeric facts into raw_xbrl_facts
            # This happens BEFORE canonical filtering
            raw_inserted = 0
            raw_skipped = 0

            print(f"\nPHASE 1: Inserting raw XBRL facts...")
            for fact in facts:
                if fact.isNil:
                    raw_skipped += 1
                    continue

                # Insert raw fact (handles all numeric facts)
                if insert_raw_fact_from_arelle(fact, model_xbrl, company, url):
                    raw_inserted += 1
                else:
                    raw_skipped += 1

            print(f"Raw facts: {raw_inserted} inserted, {raw_skipped} skipped")

            # PHASE 2: Canonical reduction for financial_facts table
            # This is the EXISTING logic - unchanged
            print(f"\nPHASE 2: Canonical reduction for financial_facts...")
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

    # PHASE 1: Insert ALL numeric facts into raw_xbrl_facts
    # This happens BEFORE canonical filtering
    raw_inserted = 0
    raw_skipped = 0

    print(f"\nPHASE 1: Inserting raw XBRL facts...")
    for fact in model_xbrl.facts:
        if fact.isNil:
            raw_skipped += 1
            continue

        # Insert raw fact (handles all numeric facts)
        if insert_raw_fact_from_arelle(fact, model_xbrl, company, str(path)):
            raw_inserted += 1
        else:
            raw_skipped += 1

    print(f"Raw facts: {raw_inserted} inserted, {raw_skipped} skipped")

    # PHASE 2: Canonical reduction for financial_facts table
    # This is the EXISTING logic - unchanged
    print(f"\nPHASE 2: Canonical reduction for financial_facts...")
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


# ----------------------------
# Raw Fact Extraction Helpers
# ----------------------------

def extract_dimensions_json(ctx) -> str:
    """
    Extract dimensional qualifiers from context as JSON string.

    XBRL dimensions include segments, scenarios, and typed/explicit members.
    We preserve these for future analysis without interpreting them.
    """
    if ctx is None or not hasattr(ctx, 'qnameDims'):
        return "{}"

    dims = {}
    try:
        for dim_qname, member in ctx.qnameDims.items():
            dim_key = dim_qname.localName if hasattr(dim_qname, 'localName') else str(dim_qname)
            if hasattr(member, 'memberQname'):
                dims[dim_key] = member.memberQname.localName
            elif hasattr(member, 'typedMember'):
                dims[dim_key] = str(member.typedMember)
            else:
                dims[dim_key] = str(member)
    except Exception:
        pass

    return json.dumps(dims, sort_keys=True)


def compute_context_hash(ctx) -> str:
    """
    Compute a hash of the context to enable deduplication.

    Hash includes:
    - Period (start/end or instant)
    - Dimensions
    - Entity identifier
    """
    if ctx is None:
        return ""

    hash_parts = []

    # Period
    if ctx.startDatetime and ctx.endDatetime:
        hash_parts.append(f"duration:{ctx.startDatetime.isoformat()}:{ctx.endDatetime.isoformat()}")
    elif ctx.instantDatetime:
        hash_parts.append(f"instant:{ctx.instantDatetime.isoformat()}")

    # Entity
    if hasattr(ctx, 'entityIdentifier') and ctx.entityIdentifier:
        hash_parts.append(f"entity:{ctx.entityIdentifier[1]}")

    # Dimensions
    dims_json = extract_dimensions_json(ctx)
    if dims_json != "{}":
        hash_parts.append(f"dims:{dims_json}")

    hash_string = "|".join(hash_parts)
    return hashlib.sha256(hash_string.encode()).hexdigest()[:16]


def extract_period_info(ctx):
    """
    Extract period type, dates, and fiscal year from context.

    Returns: (period_type, start_date, end_date, fiscal_year)
    """
    if ctx is None:
        return None, None, None, None

    if ctx.startDatetime and ctx.endDatetime:
        return (
            "duration",
            ctx.startDatetime.date().isoformat(),
            ctx.endDatetime.date().isoformat(),
            ctx.endDatetime.year
        )
    elif ctx.instantDatetime:
        return (
            "instant",
            None,
            ctx.instantDatetime.date().isoformat(),
            ctx.instantDatetime.year
        )
    else:
        return None, None, None, None


def insert_raw_fact_from_arelle(fact, model_xbrl, company: str, filing_source: str):
    """
    Insert a raw XBRL fact into raw_xbrl_facts table.

    This is called for ALL numeric facts BEFORE canonical filtering.
    """
    try:
        # Extract numeric value
        try:
            numeric_value = float(fact.value)
        except (TypeError, ValueError):
            return False

        # Extract concept information
        concept_qname = str(fact.qname)
        concept_local_name = fact.qname.localName
        concept_namespace = fact.qname.namespaceURI

        # Extract unit
        unit = None
        if fact.unit:
            try:
                # Unit measures are stored as a frozenset of QNames
                measures = fact.unit.measures[0] if fact.unit.measures else []
                if measures:
                    unit = measures[0].localName if hasattr(measures[0], 'localName') else str(measures[0])
            except Exception:
                unit = str(fact.unit)

        # Extract context
        ctx = model_xbrl.contexts.get(fact.contextID)
        if ctx is None:
            return False

        # Extract period info
        period_type, start_date, end_date, fiscal_year = extract_period_info(ctx)
        if period_type is None:
            return False

        # Extract dimensions
        dimensions = extract_dimensions_json(ctx)
        is_consolidated = is_consolidated_context(ctx)

        # Compute context hash
        context_hash = compute_context_hash(ctx)

        # Insert raw fact
        insert_raw_xbrl_fact(
            concept_qname=concept_qname,
            concept_local_name=concept_local_name,
            concept_namespace=concept_namespace,
            numeric_value=numeric_value,
            unit=unit,
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            fiscal_year=fiscal_year,
            context_id=fact.contextID,
            context_hash=context_hash,
            dimensions=dimensions,
            is_consolidated=is_consolidated,
            company=company,
            filing_source=filing_source
        )

        return True

    except Exception:
        # Silently skip facts that fail to parse
        return False


# ----------------------------
# CLI Entrypoint
# ----------------------------

def main():
    """
    CLI entrypoint for XBRL ingestion.

    Supports both:
    1. Local file ingestion: --company <name> --file <path>
    2. SEC download ingestion: --company <name> --cik <cik> --years <year1> <year2>
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest XBRL filings into raw_xbrl_facts and financial_facts tables"
    )

    parser.add_argument(
        "--company",
        required=True,
        help="Company name (e.g., 'Microsoft', 'Apple Inc')"
    )

    parser.add_argument(
        "--file",
        help="Path to local XBRL/iXBRL file (HTML or XML)"
    )

    parser.add_argument(
        "--cik",
        help="SEC CIK number (used with --years for SEC downloads)"
    )

    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Fiscal years to download from SEC (e.g., 2022 2023)"
    )

    args = parser.parse_args()

    # Route to appropriate ingestion function
    if args.file:
        # Local file ingestion
        print(f"Ingesting local XBRL file: {args.file}")
        ingest_local_xbrl_file(
            file_path=args.file,
            company=args.company,
            years=args.years
        )

    elif args.cik and args.years:
        # SEC download ingestion
        print(f"Ingesting from SEC for {args.company} (CIK: {args.cik})")
        ingest_company_xbrl(
            company=args.company,
            cik=args.cik,
            years=args.years
        )

    else:
        parser.error("Must provide either --file, or both --cik and --years")


if __name__ == "__main__":
    main()