import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../sql_course/agent.db")

def query_financial_fact(metric: str, year: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT value
        FROM financial_facts
        WHERE metric = ? AND year = ?
    """, (metric, year))

    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def query_aggregate(metric: str, agg: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT {agg}(value)
        FROM financial_facts
        WHERE metric = ?
    """, (metric,))

    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None