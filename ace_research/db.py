import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../sql_course/agent.db")

def query_financial_fact(metric: str, year: int, company: str = "ACME Corp"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT value
        FROM financial_facts
        WHERE metric = ? AND year = ? AND company = ?
    """, (metric, year, company))

    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_canonical_financial_fact(metric: str, year: int, company: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT MAX(value)
        FROM financial_facts
        WHERE metric = ? AND year = ? AND company = ?
    """, (metric, year, company))

    row = cursor.fetchone()
    conn.close()

    return row[0] if row and row[0] is not None else None

def get_canonical_timeseries(company: str, metric: str, years: list[int]):
    """
    Returns a list of (year, value) pairs using canonical facts only.
    """
    series = []
    for year in sorted(years):
        value = get_canonical_financial_fact(metric, year, company)
        if value is not None:
            series.append((year, value))
    return series

def get_all_canonical_facts(company: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT company, year, metric, MAX(value) as value
        FROM financial_facts
        WHERE company = ?
        GROUP BY company, year, metric
        ORDER BY year, metric
    """, (company,))

    rows = cursor.fetchall()
    conn.close()
    return rows

def query_aggregate(metric: str, agg: str, year: int, company: str = "ACME Corp"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT {agg}(value)
        FROM financial_facts
        WHERE metric = ? AND year = ? AND company = ?
    """, (metric, year, company))

    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_confidence_history():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT question, confidence, timestamp
        FROM agent_predictions
        ORDER BY timestamp ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_available_years(company=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if company is None:
        cur.execute(
            "SELECT DISTINCT year FROM financial_facts ORDER BY year"
        )
    else:
        cur.execute(
            "SELECT DISTINCT year FROM financial_facts WHERE company = ? ORDER BY year",
            (company,)
        )

    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_available_metrics():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT metric FROM financial_facts")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_available_aggregations():
    return ["SUM", "AVG", "MIN", "MAX", "COUNT"]

def get_available_companies():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT company
        FROM financial_facts
        WHERE company IS NOT NULL
        ORDER BY company
    """)

    rows = cursor.fetchall()
    conn.close()

    return [row[0] for row in rows]

def query_metric_over_years(metric: str, company: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT year, value
        FROM financial_facts
        WHERE metric = ? AND company = ?
        ORDER BY year
    """, (metric, company))

    rows = cursor.fetchall()
    conn.close()
    return rows

def insert_financial_fact(company: str, year: int, metric: str, value: float):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO financial_facts (company, year, metric, value)
        VALUES (?, ?, ?, ?)
    """, (company, year, metric, value))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    print(query_financial_fact("revenue", 2023))
    print(query_aggregate("revenue", "SUM", 2023))