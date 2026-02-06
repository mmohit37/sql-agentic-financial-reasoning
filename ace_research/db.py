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

def insert_raw_xbrl_fact(
    concept_qname: str,
    concept_local_name: str,
    concept_namespace: str,
    numeric_value: float,
    unit: str,
    period_type: str,
    start_date: str,
    end_date: str,
    fiscal_year: int,
    context_id: str,
    context_hash: str,
    dimensions: str,
    is_consolidated: bool,
    company: str,
    filing_source: str
):
    """
    Insert a raw XBRL fact before canonical reduction.

    This preserves ALL numeric facts from filings, including:
    - All concept variants
    - All dimensional slices
    - All period types
    - All contexts

    Canonical reduction happens downstream in financial_facts table.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO raw_xbrl_facts (
            concept_qname,
            concept_local_name,
            concept_namespace,
            numeric_value,
            unit,
            period_type,
            start_date,
            end_date,
            fiscal_year,
            context_id,
            context_hash,
            dimensions,
            is_consolidated,
            company,
            filing_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        concept_qname,
        concept_local_name,
        concept_namespace,
        numeric_value,
        unit,
        period_type,
        start_date,
        end_date,
        fiscal_year,
        context_id,
        context_hash,
        dimensions,
        1 if is_consolidated else 0,
        company,
        filing_source
    ))

    conn.commit()
    conn.close()

# ----------------------------
# Year-over-Year Helpers (Reuse Existing Functions)
# ----------------------------

def get_metric_previous_year(metric: str, year: int, company: str):
    """
    Get metric value for the previous year (year - 1).

    This is a thin wrapper around get_canonical_financial_fact().
    Returns None if prior year data is unavailable.
    """
    prior_year = year - 1
    return get_canonical_financial_fact(metric, prior_year, company)


def get_metric_delta(metric: str, year: int, company: str):
    """
    Compute year-over-year delta: value(t) - value(t-1).

    Composes get_canonical_financial_fact() for both years.
    Returns None if either year is missing.
    """
    current = get_canonical_financial_fact(metric, year, company)
    prior = get_metric_previous_year(metric, year, company)

    if current is None or prior is None:
        return None

    return current - prior


def get_metric_ratio(numerator_metric: str, denominator_metric: str, year: int, company: str):
    """
    Compute ratio: numerator / denominator.

    Composes get_canonical_financial_fact() for both components.
    Returns None if either component is missing or denominator is zero.

    Examples:
        - ROA: get_metric_ratio("net_income", "total_assets", 2023, "Microsoft")
        - Current ratio: get_metric_ratio("current_assets", "current_liabilities", 2023, "Microsoft")
    """
    numerator = get_canonical_financial_fact(numerator_metric, year, company)
    denominator = get_canonical_financial_fact(denominator_metric, year, company)

    if numerator is None or denominator is None:
        return None

    if denominator == 0:
        return None

    return numerator / denominator


# ----------------------------
# Derived Metrics Storage
# ----------------------------

def insert_derived_metric(
    company: str,
    year: int,
    metric: str,
    value: float,
    metric_type: str,
    input_components: str
):
    """
    Insert a derived metric with explicit provenance.

    Args:
        company: Company name
        year: Fiscal year
        metric: Derived metric name (e.g., "roa", "revenue_delta")
        value: Computed value (or None if computation failed)
        metric_type: One of "ratio", "delta", "single_year"
        input_components: JSON string documenting which canonical metrics were used

    This function does NOT compute metrics - it only stores pre-computed values.
    Computation should happen explicitly in calling code using get_metric_ratio(), etc.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO derived_metrics (
            company,
            year,
            metric,
            value,
            metric_type,
            input_components
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (company, year, metric, value, metric_type, input_components))

    conn.commit()
    conn.close()


def get_derived_metric(metric: str, year: int, company: str):
    """
    Retrieve a previously computed derived metric.

    Returns None if not found or if computation failed (value IS NULL).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT value
        FROM derived_metrics
        WHERE metric = ? AND year = ? AND company = ?
    """, (metric, year, company))

    row = cursor.fetchone()
    conn.close()

    return row[0] if row else None


if __name__ == "__main__":
    print(query_financial_fact("revenue", 2023))
    print(query_aggregate("revenue", "SUM", 2023))