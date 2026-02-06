# Raw XBRL Facts Extension - Implementation Summary

## Overview

Extended the XBRL ingestion pipeline to preserve **ALL numeric XBRL facts** in a new `raw_xbrl_facts` table BEFORE canonical reduction. This follows Agentic Context Engineering principles by preserving information rather than discarding it early.

## What Was Changed

### 1. Database Schema (`migrations/001_add_raw_xbrl_facts.sql`)

Created new table `raw_xbrl_facts` that stores:
- **Concept information**: QName, local name, namespace
- **Numeric value and unit**: The actual value and its unit (USD, shares, etc.)
- **Period information**: Type (instant/duration), start/end dates, fiscal year
- **Context metadata**: Context ID, hash for deduplication
- **Dimensional qualifiers**: Stored as JSON (segments, scenarios, etc.)
- **Filing metadata**: Company, source URL/path, ingestion timestamp

**Key indexes** for efficient querying:
- Company + fiscal year
- Concept local name
- Context hash
- Consolidated facts (for quick canonical filtering)

**Unique constraint**: Prevents duplicate ingestion of same fact from same filing

### 2. Database Functions (`ace_research/db.py`)

Added `insert_raw_xbrl_fact()` function that:
- Accepts all raw fact metadata
- Uses `INSERT OR IGNORE` to handle duplicates gracefully
- Maps boolean `is_consolidated` to SQLite integer (0/1)

### 3. Helper Functions (`ace_research/xbrl/ingest.py`)

Added 4 new helper functions:

1. **`extract_dimensions_json(ctx)`**
   - Extracts dimensional qualifiers from context
   - Returns JSON string of dimensions
   - Handles typed and explicit members

2. **`compute_context_hash(ctx)`**
   - Creates SHA256 hash of context attributes
   - Includes period, entity, and dimensions
   - Enables deduplication and fast lookups

3. **`extract_period_info(ctx)`**
   - Determines period type (instant vs duration)
   - Extracts start/end dates in ISO 8601 format
   - Infers fiscal year from end date

4. **`insert_raw_fact_from_arelle(fact, model_xbrl, company, filing_source)`**
   - Main coordinator function
   - Extracts all metadata from Arelle fact object
   - Calls `insert_raw_xbrl_fact()` with extracted data
   - Returns True/False for success/failure

### 4. Ingestion Pipeline Modifications

Both `ingest_company_xbrl()` and `ingest_local_xbrl_file()` now have **TWO PHASES**:

**PHASE 1: Raw Fact Insertion** (NEW)
```python
# Insert ALL numeric facts into raw_xbrl_facts
for fact in facts:
    if fact.isNil:
        continue
    insert_raw_fact_from_arelle(fact, model_xbrl, company, filing_source)
```

**PHASE 2: Canonical Reduction** (UNCHANGED)
```python
# Existing logic for canonical fact selection
for fact in facts:
    # Apply filters:
    # - Must be in XBRL_METRIC_MAP
    # - Must be full-year duration
    # - Must be consolidated context
    # - Take max value for duplicates

    canonical_facts[(company, year, metric)] = max_value

# Insert into financial_facts table
```

## Where Canonical Reduction Happens

Canonical reduction occurs in **PHASE 2** of ingestion, specifically at these points:

### Line 157-185 in `ingest_company_xbrl()`:
```python
# Filter 1: Concept must be in XBRL_METRIC_MAP
if concept not in XBRL_METRIC_MAP:
    skipped += 1
    continue

# Filter 2: Must be full-year duration (~365 days)
if not is_full_year_context(ctx):
    skipped += 1
    continue

# Filter 3: Must be consolidated (no dimensions)
if not is_consolidated_context(ctx):
    skipped += 1
    continue

# Filter 4: Year must match requested years
if years and year not in years:
    skipped += 1
    continue
```

### Line 202-211 in `ingest_company_xbrl()`:
```python
# Deduplication: Keep max absolute value
key = (company, year, metric)
if key not in canonical_facts:
    canonical_facts[key] = value
else:
    canonical_facts[key] = max(
        canonical_facts[key],
        value,
        key=lambda v: abs(v)
    )
```

### Line 275-301 in `ingest_local_xbrl_file()`:
Similar filtering logic but less strict:
- Filter 1: Concept must be in XBRL_METRIC_MAP
- Filter 2: Must have valid year from context
- Filter 3: Year must match requested years (if specified)
- No full-year or consolidated requirements (more permissive)

## Architecture Guarantees Preserved

✅ **SQL remains source of truth**: Both tables are SQL-based
✅ **financial_facts unchanged**: Same schema, same logic, same results
✅ **No LLMs in ingestion**: Pure deterministic parsing
✅ **Changes are additive**: New table + new functions, no deletions
✅ **Reversible**: Can drop raw_xbrl_facts without affecting canonical pipeline
✅ **Information preserved**: No compression or summarization in raw table

## Data Flow Diagram

```
┌─────────────────┐
│  XBRL Filing    │
│  (SEC/Local)    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│   Arelle Parser             │
│   - Loads facts             │
│   - Parses contexts         │
│   - Extracts dimensions     │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  PHASE 1: Raw Insertion     │
│  ┌───────────────────────┐  │
│  │ ALL numeric facts     │  │
│  │ ↓                     │  │
│  │ raw_xbrl_facts table  │  │
│  └───────────────────────┘  │
│  - No filtering            │
│  - All dimensions          │
│  - All periods             │
│  - All contexts            │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  PHASE 2: Canonical Filter  │
│  ┌───────────────────────┐  │
│  │ Filter by:            │  │
│  │ - Mapped concepts     │  │
│  │ - Full-year duration  │  │
│  │ - Consolidated only   │  │
│  │ - Deduplicate         │  │
│  │ ↓                     │  │
│  │ financial_facts table │  │
│  └───────────────────────┘  │
│  - One value per metric    │
│  - Clean, queryable        │
│  - Backward compatible     │
└─────────────────────────────┘
```

## Test Coverage

Created comprehensive test suite (`tests/test_raw_xbrl_ingestion.py`) with 8 tests:

1. ✅ `test_extract_dimensions_json` - Dimension extraction works
2. ✅ `test_extract_period_info` - Period parsing works for instant/duration
3. ✅ `test_compute_context_hash` - Hashing is consistent and unique
4. ✅ `test_insert_raw_xbrl_fact` - Raw fact insertion works
5. ✅ `test_raw_fact_insertion_preserves_all_facts` - ALL facts preserved (3 raw, 1 canonical)
6. ✅ `test_raw_facts_preserve_dimensions` - Dimensional data stored correctly
7. ✅ `test_canonical_facts_unchanged` - Backward compatibility verified
8. ✅ `test_raw_facts_unique_constraint` - Deduplication works

**All tests passing**: 8/8 ✓
**Existing tests passing**: 3/3 ✓ (no regressions)

## Benefits

### Immediate
1. **Audit trail**: Can verify which facts were selected for canonical metrics
2. **Debugging**: Can investigate discrepancies in reported values
3. **No re-downloads**: Can re-map metrics without fetching filings again

### Future
1. **Richer analysis**: Can analyze segment-specific or quarterly facts
2. **Dimensional queries**: Can filter by segments, scenarios, etc.
3. **Alternative mappings**: Can create different canonical views
4. **ML training data**: Raw facts provide richer dataset for models

## Migration Instructions

### To Apply
```bash
cat migrations/001_add_raw_xbrl_facts.sql | sqlite3 sql_course/agent.db
```

### To Verify
```bash
sqlite3 sql_course/agent.db "SELECT COUNT(*) FROM raw_xbrl_facts;"
```

### To Rollback (if needed)
```bash
sqlite3 sql_course/agent.db "DROP TABLE IF EXISTS raw_xbrl_facts;"
```

## Usage Examples

### Query all raw facts for a company
```sql
SELECT
    concept_local_name,
    numeric_value,
    unit,
    period_type,
    fiscal_year,
    is_consolidated
FROM raw_xbrl_facts
WHERE company = 'Apple Inc'
    AND fiscal_year = 2023
ORDER BY concept_local_name;
```

### Compare raw vs canonical
```sql
-- How many Revenue facts before reduction?
SELECT COUNT(*)
FROM raw_xbrl_facts
WHERE concept_local_name IN ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax')
    AND fiscal_year = 2023;

-- How many after?
SELECT COUNT(*)
FROM financial_facts
WHERE metric = 'revenue'
    AND year = 2023;
```

### Find segment-specific facts
```sql
SELECT
    concept_local_name,
    numeric_value,
    dimensions
FROM raw_xbrl_facts
WHERE is_consolidated = 0
    AND company = 'Apple Inc'
    AND fiscal_year = 2023;
```

## Files Modified

1. ✅ **ace_research/xbrl/ingest.py** - Added helpers + 2-phase ingestion
2. ✅ **ace_research/db.py** - Added `insert_raw_xbrl_fact()`

## Files Created

1. ✅ **migrations/001_add_raw_xbrl_facts.sql** - Table schema + indexes
2. ✅ **tests/test_raw_xbrl_ingestion.py** - Test suite (8 tests)
3. ✅ **RAW_XBRL_FACTS_SUMMARY.md** - This document

## Next Steps (Optional Enhancements)

1. **Query functions**: Add `get_raw_facts_by_concept()`, etc. to db.py
2. **Analysis tools**: Create scripts to analyze dimensional slices
3. **Remapping tool**: Build UI to create alternative metric mappings
4. **Quarterly facts**: Extend to handle Q1/Q2/Q3/Q4 periods
5. **Dimension indices**: Add GIN index for JSON dimension queries (if using PostgreSQL)

---

**Implementation Date**: 2026-02-05
**Status**: ✅ Complete and tested
**Backward Compatible**: ✅ Yes
**Breaking Changes**: ❌ None
