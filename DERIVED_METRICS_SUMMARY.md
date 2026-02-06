# Derived Metrics Infrastructure - Implementation Summary

## Overview

Added **structural scaffolding** for derived metrics and year-over-year reasoning WITHOUT computing any metrics automatically. This follows Agentic Context Engineering principles by creating reusable, composable helpers that preserve intermediate artifacts.

---

## Critical Design Principle: Reuse Existing Helpers

**NO new metric access logic was created.**

All new functions are **thin wrappers** around the existing `get_canonical_financial_fact()` function:

```python
# EXISTING HELPER (unchanged)
def get_canonical_financial_fact(metric: str, year: int, company: str):
    """Primary metric access function - used everywhere"""
    ...

# NEW HELPERS (thin wrappers)
def get_metric_previous_year(metric: str, year: int, company: str):
    """Wraps get_canonical_financial_fact() for year-1"""
    prior_year = year - 1
    return get_canonical_financial_fact(metric, prior_year, company)

def get_metric_delta(metric: str, year: int, company: str):
    """Composes get_canonical_financial_fact() for t and t-1"""
    current = get_canonical_financial_fact(metric, year, company)
    prior = get_metric_previous_year(metric, year, company)
    ...

def get_metric_ratio(numerator_metric: str, denominator_metric: str, year: int, company: str):
    """Composes get_canonical_financial_fact() for numerator and denominator"""
    numerator = get_canonical_financial_fact(numerator_metric, year, company)
    denominator = get_canonical_financial_fact(denominator_metric, year, company)
    ...
```

**Zero duplication. Zero SQL rewrites. Pure composition.**

---

## What Was Added

### 1. **Schema Extension** ([migrations/002_add_derived_metrics.sql](migrations/002_add_derived_metrics.sql))

New table: `derived_metrics`

**Purpose**: Store computed metrics with explicit input provenance

**Schema**:
```sql
CREATE TABLE derived_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    company TEXT NOT NULL,
    year INTEGER NOT NULL,
    metric TEXT NOT NULL,          -- e.g., "roa", "revenue_yoy_delta"

    -- Computed value
    value REAL,                     -- NULL if computation failed

    -- Type classification
    metric_type TEXT NOT NULL,      -- "ratio", "delta", "single_year"

    -- Explicit input provenance (JSON)
    input_components TEXT NOT NULL,

    -- Metadata
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(company, year, metric)
);
```

**Key properties**:
- ✅ Explicit provenance via `input_components` JSON
- ✅ Explicit failure via `NULL` value (never inferred)
- ✅ No auto-computation (empty by default)
- ✅ Deterministic (same inputs → same output)

**Example provenance formats**:
```json
// Ratio (e.g., ROA)
{
  "numerator": "net_income",
  "denominator": "total_assets"
}

// Delta (year-over-year)
{
  "current": "revenue",
  "prior": "revenue",
  "years": [2023, 2022]
}

// Single-year composite
{
  "inputs": ["metric1", "metric2", "metric3"]
}
```

### 2. **Python Helpers** ([ace_research/db.py](ace_research/db.py))

Added 5 new functions, all composing the existing `get_canonical_financial_fact()`:

#### **Year-over-Year Helpers**

```python
def get_metric_previous_year(metric: str, year: int, company: str):
    """
    Get metric value for prior year (year - 1).

    Wrapper around get_canonical_financial_fact().
    Returns None if prior year unavailable.
    """
```

```python
def get_metric_delta(metric: str, year: int, company: str):
    """
    Compute YoY delta: value(t) - value(t-1).

    Composes get_canonical_financial_fact() for both years.
    Returns None if either year missing.

    Example:
        delta = get_metric_delta("revenue", 2023, "Microsoft")
        # Returns: revenue_2023 - revenue_2022
    """
```

```python
def get_metric_ratio(numerator_metric: str, denominator_metric: str,
                     year: int, company: str):
    """
    Compute ratio: numerator / denominator.

    Composes get_canonical_financial_fact() for both components.
    Returns None if either missing or denominator is zero.

    Examples:
        roa = get_metric_ratio("net_income", "total_assets", 2023, "Microsoft")
        current_ratio = get_metric_ratio("current_assets", "current_liabilities", 2023, "Microsoft")
    """
```

#### **Storage Helpers**

```python
def insert_derived_metric(company: str, year: int, metric: str,
                          value: float, metric_type: str,
                          input_components: str):
    """
    Insert a derived metric with explicit provenance.

    Does NOT compute - only stores pre-computed values.

    Args:
        value: Computed value (or None if failed)
        metric_type: "ratio", "delta", or "single_year"
        input_components: JSON documenting which canonical metrics were used
    """
```

```python
def get_derived_metric(metric: str, year: int, company: str):
    """
    Retrieve a previously computed derived metric.

    Returns None if not found or computation failed.
    """
```

---

## Safety Guarantees

### 1. **Missing Data Handling**

All helpers return `None` explicitly when data is unavailable:

```python
# Missing prior year
delta = get_metric_delta("revenue", 2023, "New Corp")
# Returns: None (no 2022 data)

# Missing component
ratio = get_metric_ratio("net_income", "missing_metric", 2023, "Microsoft")
# Returns: None (missing_metric doesn't exist)
```

**Never inferred. Never guessed. Always explicit.**

### 2. **Division by Zero Handling**

```python
ratio = get_metric_ratio("revenue", "zero_metric", 2023, "Corp")
# Returns: None (not infinity, not exception)
```

### 3. **Partial Metric Availability**

If computing a derived metric requires 3 inputs but only 2 are available:
- Helper returns `None`
- Can still store `NULL` in `derived_metrics` table with full provenance
- Provenance documents which inputs were missing

---

## Reuse of Existing Helpers

### Existing Code That Already Uses `get_canonical_financial_fact()`

**In [ace_research/experiments.py](ace_research/experiments.py):**

```python
# Line 14: Import
from ace_research.db import get_canonical_financial_fact

# Line 301: Base metric access
value = get_canonical_financial_fact(metric, year, company)

# Line 334: Component lookup for derived metrics
def get_component_value(component: str, year: int, company: str):
    return get_canonical_financial_fact(component, year, company)

# Line 465: Trend analysis
val = get_canonical_financial_fact(metric, year, company)

# Line 568: Comparison logic
val = get_canonical_financial_fact(metric, year, company)
```

**Result**: All existing code continues to work unchanged. New helpers integrate seamlessly.

---

## Usage Examples

### Example 1: Compute ROA (Return on Assets)

```python
from ace_research.db import get_metric_ratio, insert_derived_metric
import json

# Compute ROA using helper
roa = get_metric_ratio("net_income", "total_assets", 2023, "Microsoft")

if roa is not None:
    # Store with provenance
    provenance = json.dumps({
        "numerator": "net_income",
        "denominator": "total_assets"
    })

    insert_derived_metric(
        company="Microsoft",
        year=2023,
        metric="roa",
        value=roa,
        metric_type="ratio",
        input_components=provenance
    )
else:
    # Store failure with provenance
    insert_derived_metric(
        company="Microsoft",
        year=2023,
        metric="roa",
        value=None,  # Computation failed
        metric_type="ratio",
        input_components=provenance
    )
```

### Example 2: Compute Year-over-Year Revenue Growth

```python
from ace_research.db import get_metric_delta, insert_derived_metric
import json

# Compute delta using helper
revenue_delta = get_metric_delta("revenue", 2023, "Microsoft")

# Store with provenance
provenance = json.dumps({
    "current": "revenue",
    "prior": "revenue",
    "years": [2023, 2022]
})

insert_derived_metric(
    company="Microsoft",
    year=2023,
    metric="revenue_yoy_delta",
    value=revenue_delta,
    metric_type="delta",
    input_components=provenance
)
```

### Example 3: Query Previously Computed Metric

```python
from ace_research.db import get_derived_metric

# Retrieve stored ROA
roa = get_derived_metric("roa", 2023, "Microsoft")

if roa is not None:
    print(f"ROA: {roa:.4f}")
else:
    print("ROA not computed or computation failed")
```

---

## Test Coverage

Created comprehensive test suite ([tests/test_derived_metrics.py](tests/test_derived_metrics.py)) with **13 tests**:

1. ✅ `test_get_metric_previous_year_reuses_existing_function` - Wrapper verification
2. ✅ `test_get_metric_delta_computes_yoy_change` - Delta computation
3. ✅ `test_get_metric_delta_handles_missing_prior_year` - Missing t-1
4. ✅ `test_get_metric_delta_handles_missing_current_year` - Missing t
5. ✅ `test_get_metric_ratio_computes_correctly` - Ratio computation
6. ✅ `test_get_metric_ratio_handles_missing_numerator` - Missing component
7. ✅ `test_get_metric_ratio_handles_missing_denominator` - Missing component
8. ✅ `test_get_metric_ratio_handles_zero_denominator` - Division by zero
9. ✅ `test_insert_and_retrieve_derived_metric` - Storage roundtrip
10. ✅ `test_insert_derived_metric_with_null_value` - Failed computation storage
11. ✅ `test_insert_derived_metric_delta_with_provenance` - Provenance preservation
12. ✅ `test_derived_metrics_table_empty_by_default` - No auto-computation
13. ✅ `test_existing_get_canonical_financial_fact_unchanged` - Backward compatibility

**All 24 tests passing** (11 existing + 13 new):
```
tests/test_db.py ............................ 3 passed
tests/test_derived_metrics.py .............. 13 passed
tests/test_raw_xbrl_ingestion.py ........... 8 passed

======================== 24 passed ========================
```

---

## Backward Compatibility

✅ **All existing code unchanged**
✅ **All existing tests passing**
✅ **No new SQL queries for base metric access**
✅ **Existing `get_canonical_financial_fact()` usage preserved**
✅ **No impact on ingestion pipeline**
✅ **No impact on experiments.py**

---

## What This Does NOT Do

❌ Does NOT compute Piotroski signals (structural only)
❌ Does NOT auto-populate `derived_metrics` table
❌ Does NOT modify ingestion behavior
❌ Does NOT change `financial_facts` semantics
❌ Does NOT use LLMs
❌ Does NOT infer missing data

---

## Database State After Migration

```bash
$ sqlite3 agent.db "SELECT name FROM sqlite_master WHERE type='table';"
agent_feedback
agent_playbook
agent_predictions
derived_metrics          # ← NEW (empty)
financial_facts          # ← Unchanged
raw_xbrl_facts          # ← Unchanged
```

```bash
$ sqlite3 agent.db "SELECT COUNT(*) FROM derived_metrics;"
0  # Empty by default
```

---

## Files Modified

1. ✅ [ace_research/db.py](ace_research/db.py) - Added 5 helper functions (~110 lines)

## Files Created

1. ✅ [migrations/002_add_derived_metrics.sql](migrations/002_add_derived_metrics.sql) - Schema + docs
2. ✅ [tests/test_derived_metrics.py](tests/test_derived_metrics.py) - Test suite (13 tests)
3. ✅ [DERIVED_METRICS_SUMMARY.md](DERIVED_METRICS_SUMMARY.md) - This document

---

## Key Achievement: Zero Duplication

**Before this work:**
- `get_canonical_financial_fact()` was the single source of truth for metric access

**After this work:**
- `get_canonical_financial_fact()` **remains** the single source of truth
- All new helpers **compose** it, never reimplement it
- Zero new SQL queries for base metric access
- Pure functional composition

**This is Agentic Context Engineering:**
- Incremental evolution (extend, don't rewrite)
- Preserve existing helpers (reuse, don't duplicate)
- Explicit artifacts (provenance, not inference)
- No context collapse (NULL stays NULL)

---

## Next Steps (Future Work)

1. **Piotroski Score Computation**: Use these helpers to compute 9 signals
2. **Batch Computation Script**: Populate `derived_metrics` for all companies/years
3. **Analysis Tools**: Query trends in derived metrics
4. **Visualization**: Chart YoY deltas and ratios
5. **Quality Checks**: Identify anomalous ratios or deltas

---

**Implementation Date**: 2026-02-05
**Status**: ✅ Complete and tested
**Backward Compatible**: ✅ Yes (24/24 tests passing)
**Breaking Changes**: ❌ None
**Auto-Computation**: ❌ None (structural only)
**Helper Reuse**: ✅ 100% (all new helpers wrap existing function)
