"""
Tests for raw XBRL fact ingestion pipeline.

Verifies that:
1. ALL numeric facts are preserved in raw_xbrl_facts
2. Canonical reduction still works in financial_facts
3. No data loss occurs during ingestion
4. Helper functions correctly extract metadata
"""

import pytest
import sqlite3
import tempfile
import os
from datetime import datetime
from pathlib import Path

# Mock Arelle objects for testing
class MockQName:
    def __init__(self, namespace, local_name):
        self.namespaceURI = namespace
        self.localName = local_name

    def __str__(self):
        return f"{{{self.namespaceURI}}}{self.localName}"


class MockContext:
    def __init__(self, context_id, start=None, end=None, instant=None, has_dims=False):
        self.id = context_id
        self.startDatetime = start
        self.endDatetime = end
        self.instantDatetime = instant
        self.qnameDims = {"segment": "US"} if has_dims else {}
        self.entityIdentifier = ("http://example.com", "0001234567")


class MockUnit:
    def __init__(self, measure="USD"):
        self.measures = [[MockQName("http://www.xbrl.org/2003/iso4217", measure)]]


class MockFact:
    def __init__(self, qname, value, context_id, unit=None, is_nil=False):
        self.qname = qname
        self.value = value
        self.contextID = context_id
        self.unit = unit
        self.isNil = is_nil


@pytest.fixture
def test_db():
    """Create a temporary test database with both tables"""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create financial_facts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            metric TEXT NOT NULL,
            value REAL
        )
    """)

    # Create raw_xbrl_facts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_xbrl_facts (
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

    conn.commit()
    conn.close()

    # Patch the DB_PATH
    import ace_research.db as db_module
    original_db_path = db_module.DB_PATH
    db_module.DB_PATH = db_path

    yield db_path

    # Cleanup
    db_module.DB_PATH = original_db_path
    try:
        os.unlink(db_path)
    except:
        pass


def test_extract_dimensions_json(test_db):
    """Test dimension extraction from contexts"""
    from ace_research.xbrl.ingest import extract_dimensions_json

    # No dimensions
    ctx = MockContext("ctx1")
    ctx.qnameDims = {}
    result = extract_dimensions_json(ctx)
    assert result == "{}"

    # With dimensions
    ctx = MockContext("ctx2", has_dims=True)
    result = extract_dimensions_json(ctx)
    assert result != "{}"
    assert "segment" in result


def test_extract_period_info(test_db):
    """Test period information extraction"""
    from ace_research.xbrl.ingest import extract_period_info

    # Duration context
    start = datetime(2023, 1, 1)
    end = datetime(2023, 12, 31)
    ctx = MockContext("ctx1", start=start, end=end)

    period_type, start_date, end_date, fiscal_year = extract_period_info(ctx)
    assert period_type == "duration"
    assert start_date == "2023-01-01"
    assert end_date == "2023-12-31"
    assert fiscal_year == 2023

    # Instant context
    instant = datetime(2023, 12, 31)
    ctx = MockContext("ctx2", instant=instant)

    period_type, start_date, end_date, fiscal_year = extract_period_info(ctx)
    assert period_type == "instant"
    assert start_date is None
    assert end_date == "2023-12-31"
    assert fiscal_year == 2023


def test_compute_context_hash(test_db):
    """Test context hash computation for deduplication"""
    from ace_research.xbrl.ingest import compute_context_hash

    # Same contexts should produce same hash
    ctx1 = MockContext("ctx1", instant=datetime(2023, 12, 31))
    ctx2 = MockContext("ctx2", instant=datetime(2023, 12, 31))

    hash1 = compute_context_hash(ctx1)
    hash2 = compute_context_hash(ctx2)

    # Hashes should be non-empty
    assert hash1 != ""
    assert hash2 != ""

    # Different contexts should produce different hashes
    ctx3 = MockContext("ctx3", instant=datetime(2022, 12, 31))
    hash3 = compute_context_hash(ctx3)
    assert hash1 != hash3


def test_insert_raw_xbrl_fact(test_db):
    """Test inserting raw XBRL facts"""
    from ace_research.db import insert_raw_xbrl_fact

    insert_raw_xbrl_fact(
        concept_qname="{http://fasb.org/us-gaap/2023}Assets",
        concept_local_name="Assets",
        concept_namespace="http://fasb.org/us-gaap/2023",
        numeric_value=1000000.0,
        unit="USD",
        period_type="instant",
        start_date=None,
        end_date="2023-12-31",
        fiscal_year=2023,
        context_id="ctx_123",
        context_hash="abc123def456",
        dimensions="{}",
        is_consolidated=True,
        company="Test Corp",
        filing_source="test_filing.html"
    )

    # Verify insertion
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM raw_xbrl_facts")
    count = cursor.fetchone()[0]
    assert count == 1

    cursor.execute("SELECT * FROM raw_xbrl_facts WHERE company = 'Test Corp'")
    row = cursor.fetchone()
    assert row is not None
    assert row[4] == 1000000.0  # numeric_value
    assert row[5] == "USD"  # unit
    assert row[6] == "instant"  # period_type

    conn.close()


def test_raw_fact_insertion_preserves_all_facts(test_db):
    """
    Test that raw fact insertion preserves ALL numeric facts,
    including those filtered out by canonical reduction.
    """
    from ace_research.db import insert_raw_xbrl_fact, insert_financial_fact

    # Insert 3 raw facts for the same concept but different contexts
    for i in range(3):
        insert_raw_xbrl_fact(
            concept_qname="{http://fasb.org/us-gaap/2023}Revenue",
            concept_local_name="Revenues",
            concept_namespace="http://fasb.org/us-gaap/2023",
            numeric_value=1000000.0 + (i * 100000),
            unit="USD",
            period_type="duration",
            start_date="2023-01-01",
            end_date="2023-12-31",
            fiscal_year=2023,
            context_id=f"ctx_{i}",
            context_hash=f"hash_{i}",
            dimensions="{}",
            is_consolidated=True,
            company="Test Corp",
            filing_source="test_filing.html"
        )

    # Insert only 1 canonical fact
    insert_financial_fact(
        company="Test Corp",
        year=2023,
        metric="revenue",
        value=1200000.0  # The max value
    )

    # Verify: raw_xbrl_facts has 3 rows
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM raw_xbrl_facts WHERE company = 'Test Corp'")
    raw_count = cursor.fetchone()[0]
    assert raw_count == 3, "All raw facts should be preserved"

    # Verify: financial_facts has 1 row
    cursor.execute("SELECT COUNT(*) FROM financial_facts WHERE company = 'Test Corp'")
    canonical_count = cursor.fetchone()[0]
    assert canonical_count == 1, "Only canonical fact should be in financial_facts"

    conn.close()


def test_raw_facts_preserve_dimensions(test_db):
    """Test that dimensional information is preserved in raw facts"""
    from ace_research.db import insert_raw_xbrl_fact

    # Insert fact with dimensions
    dims_json = '{"segment": "US", "scenario": "actual"}'

    insert_raw_xbrl_fact(
        concept_qname="{http://fasb.org/us-gaap/2023}Assets",
        concept_local_name="Assets",
        concept_namespace="http://fasb.org/us-gaap/2023",
        numeric_value=500000.0,
        unit="USD",
        period_type="instant",
        start_date=None,
        end_date="2023-12-31",
        fiscal_year=2023,
        context_id="ctx_segment",
        context_hash="segment_hash",
        dimensions=dims_json,
        is_consolidated=False,
        company="Test Corp",
        filing_source="test_filing.html"
    )

    # Verify dimensions are stored
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT dimensions, is_consolidated
        FROM raw_xbrl_facts
        WHERE context_id = 'ctx_segment'
    """)
    row = cursor.fetchone()
    assert row[0] == dims_json
    assert row[1] == 0  # Not consolidated

    conn.close()


def test_canonical_facts_unchanged(test_db):
    """
    Test that canonical fact insertion still works as before.
    This ensures backwards compatibility.
    """
    from ace_research.db import insert_financial_fact, get_canonical_financial_fact

    # Insert canonical facts
    insert_financial_fact("Test Corp", 2023, "revenue", 1000000.0)
    insert_financial_fact("Test Corp", 2023, "net_income", 100000.0)

    # Query canonical facts
    revenue = get_canonical_financial_fact("revenue", 2023, "Test Corp")
    net_income = get_canonical_financial_fact("net_income", 2023, "Test Corp")

    assert revenue == 1000000.0
    assert net_income == 100000.0


def test_raw_facts_unique_constraint(test_db):
    """Test that duplicate raw facts are ignored (INSERT OR IGNORE)"""
    from ace_research.db import insert_raw_xbrl_fact

    # Insert same fact twice
    for _ in range(2):
        insert_raw_xbrl_fact(
            concept_qname="{http://fasb.org/us-gaap/2023}Assets",
            concept_local_name="Assets",
            concept_namespace="http://fasb.org/us-gaap/2023",
            numeric_value=1000000.0,
            unit="USD",
            period_type="instant",
            start_date=None,
            end_date="2023-12-31",
            fiscal_year=2023,
            context_id="ctx_dup",
            context_hash="dup_hash",
            dimensions="{}",
            is_consolidated=True,
            company="Test Corp",
            filing_source="same_filing.html"
        )

    # Should only have 1 row due to UNIQUE constraint
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM raw_xbrl_facts")
    count = cursor.fetchone()[0]
    assert count == 1, "Duplicate facts should be ignored"

    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
