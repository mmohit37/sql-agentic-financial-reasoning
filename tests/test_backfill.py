"""
tests/test_backfill.py

Unit tests for the duration-aware canonical selection logic in
ace_research/xbrl/backfill.py.

_select_best() tests exercise the pure ranking function directly (no DB).
TestDimensionFiltering uses a real temp DB to verify the aggregation flow.
"""

import os
import sqlite3
import tempfile

import pytest
from ace_research.xbrl.backfill import _select_best, INSTANT_METRICS


def _row(value, start_date=None, end_date=None):
    return {"value": value, "start_date": start_date, "end_date": end_date}


# =============================================================================
# Duration metrics
# =============================================================================

class TestDurationSelection:

    def test_duration_metric_prefers_longest_period(self):
        """Full-year row wins over a quarterly row even when quarterly value is larger."""
        rows = [
            _row(500.0, "2022-01-01", "2022-12-31"),  # 364 days — full year
            _row(900.0, "2022-10-01", "2022-12-31"),  # 91 days  — quarterly (higher value)
            _row(300.0, "2022-07-01", "2022-12-31"),  # 183 days — half-year
        ]
        assert _select_best(rows, "revenue") == 500.0

    def test_duration_metric_prefers_latest_end_date_on_tie(self):
        """When two rows have equal duration, the one with the later end_date wins."""
        rows = [
            _row(100.0, "2021-01-01", "2021-12-31"),  # 364 days, ends 2021
            _row(200.0, "2022-01-01", "2022-12-31"),  # 364 days, ends 2022 (later)
        ]
        assert _select_best(rows, "revenue") == 200.0

    def test_duration_metric_fallback_without_dates(self):
        """When no row has both start+end dates, use latest end_date then largest abs."""
        rows = [
            _row(300.0, None, "2022-12-31"),
            _row(100.0, None, "2022-12-31"),  # same end_date, smaller abs
            _row(200.0, None, "2021-12-31"),  # older end_date — loses
        ]
        # Both 300 and 100 share the latest end_date; abs(300) > abs(100)
        assert _select_best(rows, "revenue") == 300.0

    def test_duration_fallback_prefers_later_end_date(self):
        """Fallback must prefer later end_date even when the older row has a larger value."""
        rows = [
            _row(999.0, None, "2021-06-30"),  # older but large
            _row(50.0,  None, "2022-12-31"),  # newer but small
        ]
        assert _select_best(rows, "net_income") == 50.0

    def test_duration_mixed_dated_and_undated(self):
        """Dated rows always beat undated rows, regardless of value magnitude."""
        rows = [
            _row(9999.0, None, "2022-12-31"),          # no start_date
            _row(100.0,  "2022-01-01", "2022-12-31"),  # full-year dated
        ]
        assert _select_best(rows, "gross_profit") == 100.0


# =============================================================================
# Instant metrics
# =============================================================================

class TestInstantSelection:

    def test_instant_metric_prefers_latest_end_date(self):
        """Instant metric selects the row with the most recent end_date."""
        rows = [
            _row(2000.0, None, "2021-12-31"),
            _row(1000.0, None, "2022-12-31"),  # later — wins regardless of value
        ]
        assert _select_best(rows, "total_assets") == 1000.0

    def test_instant_metric_tiebreak_by_abs_value(self):
        """When two instant rows share end_date, larger absolute value wins."""
        rows = [
            _row(800.0,  None, "2022-12-31"),
            _row(1200.0, None, "2022-12-31"),
        ]
        assert _select_best(rows, "total_equity") == 1200.0

    def test_all_instant_metrics_use_instant_logic(self):
        """Every metric in INSTANT_METRICS must prefer the later end_date (smoke test)."""
        rows = [
            _row(5000.0, None, "2022-12-31"),
            _row(3000.0, None, "2023-06-30"),  # later — wins
        ]
        for metric in INSTANT_METRICS:
            assert _select_best(rows, metric) == 3000.0


# =============================================================================
# Dimension filtering — exercises the full aggregation flow in
# backfill_canonical_from_raw() rather than _select_best() in isolation.
# =============================================================================

@pytest.fixture
def dim_db():
    """Temp DB with one undimensioned revenue row (168) and one segment row (69)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            metric TEXT NOT NULL,
            value REAL
        )
    """)
    cur.execute("""
        CREATE TABLE raw_xbrl_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_qname TEXT NOT NULL,
            concept_local_name TEXT NOT NULL,
            concept_namespace TEXT,
            numeric_value REAL NOT NULL,
            unit TEXT,
            period_type TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            fiscal_year INTEGER,
            context_id TEXT NOT NULL,
            context_hash TEXT,
            dimensions TEXT,
            is_consolidated BOOLEAN DEFAULT 0,
            company TEXT NOT NULL,
            filing_source TEXT,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company, filing_source, context_id, concept_local_name, numeric_value)
        )
    """)

    # Consolidated revenue — no dimensions
    cur.execute("""
        INSERT INTO raw_xbrl_facts
            (concept_qname, concept_local_name, numeric_value, unit, period_type,
             start_date, end_date, fiscal_year, context_id, dimensions,
             is_consolidated, company, filing_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "{http://fasb.org/us-gaap/2023}Revenues", "Revenues",
        168.0, "USD", "duration",
        "2021-01-01", "2021-12-31", 2021, "ctx_consolidated",
        "{}", 1, "Microsoft", "msft-2021.htm",
    ))

    # Segment revenue — dimensioned (should be excluded)
    cur.execute("""
        INSERT INTO raw_xbrl_facts
            (concept_qname, concept_local_name, numeric_value, unit, period_type,
             start_date, end_date, fiscal_year, context_id, dimensions,
             is_consolidated, company, filing_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "{http://fasb.org/us-gaap/2023}Revenues", "Revenues",
        69.0, "USD", "duration",
        "2021-01-01", "2021-12-31", 2021, "ctx_segment",
        '{"ProductAxis": "Windows"}', 1, "Microsoft", "msft-2021.htm",
    ))

    conn.commit()
    conn.close()

    import ace_research.db as db_module
    import ace_research.xbrl.backfill as backfill_module
    original_db = db_module.DB_PATH
    original_bf = backfill_module.DB_PATH
    db_module.DB_PATH = db_path
    backfill_module.DB_PATH = db_path
    yield db_path
    db_module.DB_PATH = original_db
    backfill_module.DB_PATH = original_bf
    try:
        os.unlink(db_path)
    except Exception:
        pass


class TestDimensionFiltering:

    def test_dimensioned_rows_are_ignored(self, dim_db):
        """
        Segment row (dimensions='{"ProductAxis": ...}', value=69) must be
        excluded by the Python-layer dimension filter.  Only the undimensioned
        consolidated row (value=168) should reach _select_best() and be written
        to financial_facts.
        """
        from ace_research.xbrl.backfill import backfill_canonical_from_raw

        backfill_canonical_from_raw(companies=["Microsoft"])

        conn = sqlite3.connect(dim_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM financial_facts WHERE company=? AND year=? AND metric=?",
            ("Microsoft", 2021, "revenue"),
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None, "revenue must be promoted to financial_facts"
        assert row[0] == 168.0, f"expected 168 (consolidated), got {row[0]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
