"""
Backfill canonical facts from raw_xbrl_facts.

When new entries are added to XBRL_METRIC_MAP, this module promotes
matching raw facts into financial_facts without re-downloading filings.

Only promotes consolidated, non-nil numeric facts.
Uses the same deduplication strategy as canonical ingestion:
one value per (company, year, metric), keeping the largest absolute value.
"""

import sqlite3
import os

from ace_research.xbrl.mappings import XBRL_METRIC_MAP
from ace_research.db import DB_PATH


def backfill_canonical_from_raw(companies: list[str] | None = None, dry_run: bool = False):
    """
    Scan raw_xbrl_facts and promote any facts whose concept_local_name
    maps to a canonical metric not yet present in financial_facts.

    Args:
        companies: Optional list of companies to backfill. None = all.
        dry_run: If True, print what would be inserted without writing.

    Returns:
        Number of facts promoted.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Build set of canonical metrics we want
    target_metrics = set(XBRL_METRIC_MAP.values())

    # Find which (company, year, metric) already exist in financial_facts
    cur.execute("SELECT company, year, metric FROM financial_facts")
    existing = {(row["company"], row["year"], row["metric"]) for row in cur.fetchall()}

    # Query consolidated raw facts for mapped concepts
    concept_names = list(XBRL_METRIC_MAP.keys())
    placeholders = ",".join("?" * len(concept_names))

    query = f"""
        SELECT company, fiscal_year, concept_local_name, numeric_value
        FROM raw_xbrl_facts
        WHERE is_consolidated = 1
          AND concept_local_name IN ({placeholders})
    """

    params = concept_names
    if companies:
        company_placeholders = ",".join("?" * len(companies))
        query += f" AND company IN ({company_placeholders})"
        params = concept_names + companies

    cur.execute(query, params)
    rows = cur.fetchall()

    # Aggregate: for each (company, year, metric), keep max absolute value
    candidates = {}
    for row in rows:
        concept = row["concept_local_name"]
        metric = XBRL_METRIC_MAP.get(concept)
        if metric is None:
            continue

        company = row["company"]
        year = row["fiscal_year"]
        value = row["numeric_value"]

        if year is None:
            continue

        key = (company, year, metric)

        # Skip if already in canonical
        if key in existing:
            continue

        if key not in candidates:
            candidates[key] = value
        else:
            candidates[key] = max(candidates[key], value, key=lambda v: abs(v))

    # Insert candidates
    promoted = 0
    for (company, year, metric) in sorted(candidates.keys()):
        value = candidates[(company, year, metric)]
        if dry_run:
            print(f"  [DRY RUN] Would insert: {company} | {year} | {metric} | {value}")
        else:
            cur.execute("""
                INSERT OR IGNORE INTO financial_facts (company, year, metric, value)
                VALUES (?, ?, ?, ?)
            """, (company, year, metric, value))
        promoted += 1

    if not dry_run:
        conn.commit()

    conn.close()

    print(f"Backfill complete: {promoted} facts promoted" +
          (" (dry run)" if dry_run else ""))
    return promoted


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill canonical facts from raw XBRL")
    parser.add_argument("--company", nargs="+", help="Companies to backfill (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    backfill_canonical_from_raw(companies=args.company, dry_run=args.dry_run)
