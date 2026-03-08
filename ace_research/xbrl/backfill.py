"""
Backfill canonical facts from raw_xbrl_facts.

When new entries are added to XBRL_METRIC_MAP, this module promotes
matching raw facts into financial_facts without re-downloading filings.

Only promotes consolidated, non-nil numeric facts.
Uses duration-aware canonical selection:
- Duration metrics: longest period wins; latest end_date breaks ties.
- Instant metrics: latest end_date wins; largest absolute value breaks ties.
"""

import sqlite3
import os
from datetime import date

from ace_research.xbrl.mappings import XBRL_METRIC_MAP
from ace_research.db import DB_PATH

INSTANT_METRICS = {
    "total_assets",
    "current_assets",
    "total_liabilities",
    "current_liabilities",
    "total_equity",
    "long_term_debt",
    "shares_outstanding",
}


# =============================================================================
# Selection logic
# =============================================================================

def _select_best(rows: list[dict], metric: str) -> float:
    """
    Choose the canonical value from a list of candidate rows.

    Each row is: {"value": float, "start_date": str|None, "end_date": str|None}

    Instant metrics  → latest end_date; largest absolute value breaks ties.
    Duration metrics → longest (end - start) duration; latest end_date breaks
                       ties.  Falls back to latest end_date / largest abs when
                       no row has both dates.
    """
    def _parse(s: str | None) -> date | None:
        try:
            return date.fromisoformat(s) if s else None
        except ValueError:
            return None

    if metric in INSTANT_METRICS:
        return max(rows, key=lambda r: (r["end_date"] or "", abs(r["value"])))["value"]

    # Duration metric — prefer longest period
    dated = []
    for r in rows:
        sd = _parse(r["start_date"])
        ed = _parse(r["end_date"])
        if sd is not None and ed is not None:
            dated.append((r, (ed - sd).days, ed))

    if dated:
        best = max(dated, key=lambda t: (t[1], t[2]))
        return best[0]["value"]

    # Fallback: no valid date pairs
    return max(rows, key=lambda r: (r["end_date"] or "", abs(r["value"])))["value"]


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
        SELECT company, fiscal_year, concept_local_name, numeric_value, period_type,
               start_date, end_date, dimensions
        FROM raw_xbrl_facts
        WHERE is_consolidated = 1
          AND period_type IN ('duration', 'instant')
          AND (dimensions IS NULL OR dimensions = '{{}}' OR dimensions = '')
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
        period_type = row["period_type"]

        if metric is None:
            continue

        # Defensive Python-layer dimension filter (second line of defence after SQL)
        dimensions = row["dimensions"]
        if dimensions not in (None, "", "{}", {}):
            continue

        if metric in INSTANT_METRICS and period_type != "instant":
            continue
        if metric not in INSTANT_METRICS and period_type != "duration":
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

        candidates.setdefault(key, []).append({
            "value": value,
            "start_date": row["start_date"],
            "end_date": row["end_date"],
        })

    # Insert candidates
    promoted = 0
    for (company, year, metric) in sorted(candidates.keys()):
        value = _select_best(candidates[(company, year, metric)], metric)
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
