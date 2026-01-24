"""
Basic tests for database module
"""
import pytest
import sqlite3
import os
import tempfile
from pathlib import Path


# We'll need to set up a test database
@pytest.fixture
def test_db():
    """Create a temporary test database"""
    # Create a temporary database file
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    # Set up the schema
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            source TEXT,
            filed_date TEXT
        )
    """)

    # Insert some test data
    test_data = [
        ("Test Corp", 2023, "revenue", 1000000.0, "test", "2024-01-01"),
        ("Test Corp", 2023, "net_income", 100000.0, "test", "2024-01-01"),
        ("Test Corp", 2022, "revenue", 900000.0, "test", "2023-01-01"),
        ("Another Corp", 2023, "revenue", 2000000.0, "test", "2024-01-01"),
    ]

    cursor.executemany("""
        INSERT INTO financial_facts (company, year, metric, value, source, filed_date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, test_data)

    conn.commit()
    conn.close()

    # Store original DB_PATH
    import ace_research.db as db_module
    original_db_path = db_module.DB_PATH

    # Replace with test database path
    db_module.DB_PATH = db_path

    yield db_path

    # Cleanup: restore original DB_PATH and remove test database
    db_module.DB_PATH = original_db_path
    try:
        os.unlink(db_path)
    except:
        pass


def test_query_financial_fact(test_db):
    """Test querying a financial fact"""
    from ace_research.db import query_financial_fact

    # Test successful query
    result = query_financial_fact("revenue", 2023, "Test Corp")
    assert result == 1000000.0

    # Test non-existent data
    result = query_financial_fact("revenue", 2021, "Test Corp")
    assert result is None


def test_get_canonical_financial_fact(test_db):
    """Test getting canonical financial fact"""
    from ace_research.db import get_canonical_financial_fact

    # Test successful query
    result = get_canonical_financial_fact("revenue", 2023, "Test Corp")
    assert result == 1000000.0


def test_imports_are_absolute():
    """Verify that imports in experiments.py use absolute imports"""
    experiments_path = Path(__file__).parent.parent / "ace_research" / "experiments.py"

    if experiments_path.exists():
        content = experiments_path.read_text(encoding='utf-8')

        # Check that we're using absolute imports (from ace_research.*)
        # and not relative imports (from db import, from generator import)
        assert "from ace_research.db import" in content or "import ace_research.db" in content, \
            "experiments.py should use absolute imports for db module"
        assert "from ace_research.generator import" in content or "import ace_research.generator" in content, \
            "experiments.py should use absolute imports for generator module"
