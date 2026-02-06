# Developer Onboarding Guide

Welcome to the **Financial Reasoning Agent** project! This guide will help you get up to speed quickly.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Prerequisites](#prerequisites)
3. [Installation & Setup](#installation--setup)
4. [Project Structure](#project-structure)
5. [Architecture Deep Dive](#architecture-deep-dive)
6. [Development Workflow](#development-workflow)
7. [Key Concepts](#key-concepts)
8. [API Reference](#api-reference)
9. [Testing](#testing)
10. [Common Tasks](#common-tasks)
11. [Troubleshooting](#troubleshooting)
12. [Contributing Guidelines](#contributing-guidelines)

---

## Project Overview

This project implements an **end-to-end financial reasoning agent** that answers natural language questions about company financials using SEC XBRL data. It uses the ACE (Agentic Context Engineering) framework with a Generate → Reflect → Curate loop for continuous learning.

### What It Does

- Fetches and parses SEC XBRL filings (10-K reports)
- Normalizes financial data across different filing contexts
- Answers natural language questions about company financials
- Computes derived metrics (margins, ratios, etc.)
- Analyzes trends over time
- Compares multiple companies
- Provides confidence scores and explanations
- Learns from feedback to improve accuracy

### What It Doesn't Do (Yet)

- Frontend/UI (backend only)
- Real-time data streaming
- Non-financial data analysis
- Forecasting/predictions (only historical data)

---

## Prerequisites

### Required

- **Python 3.10+** (uses type hints like `list[int]`)
- **pip** (Python package manager)
- **SQLite** (usually bundled with Python)

### Recommended

- Git (for version control)
- Virtual environment tool (venv, conda, or virtualenv)
- Code editor with Python support (VS Code, PyCharm, etc.)

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd sql_llm_project
```

### 2. Create a Virtual Environment

```bash
# Using venv (built-in)
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies

**Note:** This project currently lacks a `requirements.txt`. Install manually:

```bash
pip install arelle requests
```

**Full dependency list:**
- `arelle` - XBRL parsing library
- `requests` - HTTP library for SEC API calls
- Standard library modules (sqlite3, json, re, os, pathlib, etc.)

### 4. Initialize the Database

The database schema is defined in `sql_course/agent_schema.sql`. To create the database:

```bash
cd sql_course
sqlite3 agent.db < agent_schema.sql
```

### 5. Verify Installation

```bash
# Test the database connection
python ace_research/db.py

# Should print some sample queries (or None if no data)
```

---

## Project Structure

```
sql_llm_project/
├── ace_research/                 # Main application code
│   ├── db.py                     # Database interface layer
│   ├── experiments.py            # Core ACE agent implementation
│   ├── generator.py              # Answer formatting utilities
│   ├── xbrl/                     # XBRL ingestion module
│   │   ├── __init__.py
│   │   ├── ingest.py             # SEC XBRL fetching & parsing
│   │   └── mappings.py           # XBRL concept mappings
│   ├── paper_notes.md            # Research paper references
│   └── reproduction_plan.md      # (Currently empty)
│
├── sql_course/                   # Database & query utilities
│   ├── agent.db                  # SQLite database (production)
│   ├── agent_schema.sql          # Database schema definition
│   ├── query_db.py               # CLI for database inspection
│   └── *.sql, *.db               # Learning exercises
│
├── data/                         # Downloaded data (not in git)
│   └── sec/                      # SEC XBRL filings cache
│
├── README.md                     # Project overview
└── DEVELOPER_GUIDE.md            # This file
```

### Key Files Explained

| File | Purpose | Lines of Code |
|------|---------|---------------|
| `ace_research/db.py` | Database interface with query helpers | 162 |
| `ace_research/experiments.py` | ACE agent: Generator, Reflector, Curator | 921 |
| `ace_research/xbrl/ingest.py` | SEC XBRL download and parsing | 327 |
| `ace_research/xbrl/mappings.py` | XBRL concept → metric mappings | 25 |
| `ace_research/generator.py` | Answer formatting functions | 25 |
| `sql_course/query_db.py` | Database query CLI utility | ~100 |

---

## Architecture Deep Dive

### High-Level Data Flow

```
┌─────────────────────┐
│ SEC EDGAR (10-K)    │  User question: "What was Apple's revenue in 2023?"
│ iXBRL Filings       │                              │
└──────────┬──────────┘                              │
           │                                          │
           ▼ (1) Ingest                               │
┌─────────────────────────┐                          │
│ XBRL Ingestion Layer    │                          │
│ - Download via CIK      │                          │
│ - Parse with Arelle     │                          │
│ - Extract facts         │                          │
│ - Filter contexts       │                          │
└──────────┬──────────────┘                          │
           │                                          │
           ▼ (2) Normalize                            │
┌─────────────────────────┐                          │
│ Canonical Normalization │                          │
│ - Map XBRL concepts     │                          │
│ - Deduplicate           │                          │
│ - Select MAX(abs(val))  │                          │
└──────────┬──────────────┘                          │
           │                                          │
           ▼ (3) Store                                │
┌─────────────────────────┐                          │
│ SQLite Database         │◄─────────────────────────┘
│ - financial_facts       │          (4) Query
│ - agent_predictions     │
│ - agent_feedback        │
│ - agent_playbook        │
└──────────┬──────────────┘
           │
           ▼ (5) Reason
┌─────────────────────────┐
│ Reasoning Engine        │
│ - Intent detection      │
│ - Metric computation    │
│ - Trend analysis        │
│ - Company comparison    │
└──────────┬──────────────┘
           │
           ▼ (6) Confidence
┌─────────────────────────┐
│ Confidence Scoring      │
│ - Base: 1.0             │
│ - Penalties applied     │
│ - Explanation generated │
└──────────┬──────────────┘
           │
           ▼ (7) Output
┌─────────────────────────┐
│ Structured Answer       │
│ {                       │
│   "answer": value,      │
│   "confidence": 0.85,   │
│   "label": "high",      │
│   "explanation": "..."  │
│ }                       │
└─────────────────────────┘
```

### ACE Framework Loop

The project implements the **ACE (Agentic Context Engineering)** pattern:

1. **Generator**: Processes user question → produces answer with confidence
2. **Reflector**: Compares prediction vs ground truth → extracts insights
3. **Curator**: Merges insights into playbook → updates learned rules

```python
# Simplified ACE loop
for sample in dataset:
    # GENERATE
    prediction = generator.generate(sample["question"])

    # REFLECT
    reflection = reflector.reflect(prediction, sample["ground_truth"])

    # CURATE
    playbook = curator.curate(playbook, reflection)

    # STORE
    store_prediction(prediction)
    store_feedback(reflection)
```

### Database Schema

```sql
-- Core financial data
financial_facts (id, company, year, metric, value)

-- Agent predictions log
agent_predictions (id, question, predicted_answer, timestamp)

-- Feedback/evaluation
agent_feedback (prediction_id, correct_answer, is_correct)

-- Learned rules
agent_playbook (id, rule)
```

---

## Development Workflow

### 1. Ingesting New Financial Data

To add a new company's data:

```python
from ace_research.xbrl.ingest import ingest_company_10k_from_sec

# Method 1: From SEC API (requires CIK)
cik = "0000320193"  # Apple's CIK
years = [2021, 2022, 2023]
ingest_company_10k_from_sec(cik, years, company_name="Apple Inc.")

# Method 2: From local iXBRL file
from ace_research.xbrl.ingest import ingest_from_local_ixbrl_file
ingest_from_local_ixbrl_file("path/to/filing.htm", company_name="Apple Inc.")
```

**How to find a company's CIK:**
1. Go to https://www.sec.gov/edgar/searchedgar/companysearch.html
2. Search for company name
3. CIK is shown in search results (10-digit number with leading zeros)

### 2. Adding New Derived Metrics

Edit `ace_research/experiments.py`:

```python
derived_metrics = {
    "operating_margin": {
        "formula": "operating_income / revenue",
        "components": ["operating_income", "revenue"]
    },
    "your_new_metric": {
        "formula": "numerator / denominator",  # Must be valid Python expression
        "components": ["numerator", "denominator"]  # Required base metrics
    }
}
```

**Rules for formulas:**
- Use Python arithmetic operators: `+`, `-`, `*`, `/`, `**`
- Reference components by their metric names (must exist in `components` list)
- Avoid division by zero (add checks if needed)

### 3. Adding New XBRL Mappings

When you encounter unmapped XBRL concepts in filings, add them to `ace_research/xbrl/mappings.py`:

```python
XBRL_METRIC_MAP = {
    # Existing mappings
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",

    # Add your new mapping
    "YourNewXBRLConcept": "your_standardized_metric_name",
}
```

**How to find XBRL concept names:**
1. Download a filing's iXBRL file
2. Open in a text editor and search for `<ix:` tags
3. Look for concept attributes like `us-gaap:Revenues`

### 4. Running the Agent

```python
from ace_research.experiments import Generator

# Initialize generator
gen = Generator()

# Ask a question
question = "What was Apple's revenue in 2023?"
result = gen.generate(question)

print(result)
# Output:
# {
#   "answer": 383933000000,
#   "confidence": 1.0,
#   "confidence_label": "high",
#   "explanation": "Direct fact lookup for base metric."
# }
```

### 5. Querying the Database

```bash
# Use the provided CLI tool
python sql_course/query_db.py "What is Apple's revenue for 2023?"

# Or use the Python API
from ace_research.db import query_financial_fact
value = query_financial_fact("revenue", 2023, "Apple Inc.")
```

---

## Key Concepts

### 1. Canonical Facts

XBRL filings contain **duplicate facts** across different contexts (consolidated, subsidiary, quarterly, annual, etc.). The ingestion layer:

1. Filters to **full-year, consolidated** contexts only
2. If duplicates remain, selects **MAX(abs(value))**
3. Stores as "canonical" fact in database

**Example:**
```
Raw XBRL facts:
  Revenue (consolidated, FY2023): 383,933M
  Revenue (US only, FY2023): 150,000M
  Revenue (quarterly sum, FY2023): 383,933M

Canonical fact stored: 383,933M
```

**Limitation:** Loses information about variance/uncertainty.

### 2. Derived Metrics

Computed from base metrics using formulas:

```python
# Base metrics (from XBRL)
revenue = 100
operating_income = 20

# Derived metric
operating_margin = operating_income / revenue  # 0.20 = 20%
```

**Current supported derived metrics (13 total):**
- Margins: operating_margin, net_margin, gross_margin
- Returns: roa (Return on Assets), roe (Return on Equity)
- Ratios: debt_to_equity, current_ratio, quick_ratio
- Per-share: earnings_per_share, book_value_per_share
- Efficiency: asset_turnover, inventory_turnover, receivables_turnover

### 3. Intent Detection

The generator infers user intent via keyword matching and regex:

| Intent Type | Keywords/Patterns | Example Question |
|-------------|-------------------|------------------|
| Base metric | "revenue", "income" | "What is Apple revenue in 2023?" |
| Derived metric | "margin", "ratio" | "What is Apple's operating margin?" |
| Trend | "trend", "change", "over time" | "How has revenue changed?" |
| Comparison | "compare", "vs", "versus", "higher" | "Which company has higher revenue?" |

### 4. Confidence Scoring

Starts at 1.0, applies penalties:

```python
confidence = 1.0
if used_aggregation:      confidence -= 0.1   # e.g., SUM, AVG
if is_derived_metric:     confidence -= 0.3   # computed, not direct fact
if missing_components:    confidence -= 0.4   # incomplete data

confidence = max(0.2, confidence)  # Floor at 0.2

# Labels
if confidence >= 0.8:     label = "high"
elif confidence >= 0.5:   label = "medium"
else:                     label = "low"
```

**Limitations:**
- Binary penalties, not probabilistic
- Doesn't account for data quality or freshness
- No uncertainty propagation

### 5. Trend Analysis

For multi-year trends, computes year-over-year differences:

```python
# Example data
years = [2021, 2022, 2023]
values = [100, 120, 150]

# Compute diffs
diffs = [20, 30]  # 120-100, 150-120

# Classify trend
if all(d > 0 for d in diffs):
    trend = "increasing"
elif all(d < 0 for d in diffs):
    trend = "decreasing"
else:
    trend = "mixed"
```

**Limitations:**
- Doesn't detect non-linear patterns (exponential, cyclical)
- No statistical significance testing
- Sensitive to outliers

---

## API Reference

### Database Layer (`ace_research/db.py`)

#### `query_financial_fact(metric: str, year: int, company: str = "ACME Corp") -> float | None`

Retrieves a single financial fact.

```python
revenue = query_financial_fact("revenue", 2023, "Apple Inc.")
# Returns: 383933000000.0 or None if not found
```

#### `get_canonical_financial_fact(metric: str, year: int, company: str) -> float | None`

Returns the canonical (deduplicated) value using MAX aggregation.

```python
canonical_revenue = get_canonical_financial_fact("revenue", 2023, "Apple Inc.")
```

#### `get_canonical_timeseries(company: str, metric: str, years: list[int]) -> list[tuple[int, float]]`

Returns time series data for trend analysis.

```python
series = get_canonical_timeseries("Apple Inc.", "revenue", [2021, 2022, 2023])
# Returns: [(2021, 365817000000), (2022, 394328000000), (2023, 383933000000)]
```

#### `get_available_companies() -> list[str]`

Lists all companies in the database.

```python
companies = get_available_companies()
# Returns: ["Apple Inc.", "Microsoft Corp.", ...]
```

#### `get_available_metrics() -> list[str]`

Lists all metrics in the database.

```python
metrics = get_available_metrics()
# Returns: ["revenue", "net_income", "total_assets", ...]
```

#### `insert_financial_fact(company: str, year: int, metric: str, value: float)`

Inserts or updates a financial fact.

```python
insert_financial_fact("Apple Inc.", 2023, "revenue", 383933000000)
```

### XBRL Ingestion (`ace_research/xbrl/ingest.py`)

#### `ingest_company_10k_from_sec(cik: str, years: list[int], company_name: str)`

Downloads and ingests 10-K filings from SEC EDGAR.

```python
ingest_company_10k_from_sec("0000320193", [2021, 2022, 2023], "Apple Inc.")
```

**Parameters:**
- `cik`: 10-digit CIK with leading zeros
- `years`: List of fiscal years to fetch
- `company_name`: Human-readable company name

**Side effects:**
- Downloads filings to `data/sec/{cik}/{year}/`
- Inserts facts into database

#### `ingest_from_local_ixbrl_file(file_path: str, company_name: str)`

Parses a local iXBRL file and ingests facts.

```python
ingest_from_local_ixbrl_file("data/apple_10k_2023.htm", "Apple Inc.")
```

### Reasoning Engine (`ace_research/experiments.py`)

#### `Generator.generate(question: str) -> dict`

Processes a natural language question and returns an answer.

```python
gen = Generator()
result = gen.generate("What was Apple's revenue in 2023?")

# Returns:
# {
#   "answer": 383933000000,
#   "confidence": 1.0,
#   "confidence_label": "high",
#   "explanation": "Direct fact lookup for base metric."
# }
```

**Return structure:**
- `answer`: Value (number, string, or dict for comparisons)
- `confidence`: Float between 0.2 and 1.0
- `confidence_label`: "high", "medium", or "low"
- `explanation`: Human-readable explanation

---

## Testing

**Current status:** ⚠️ No automated tests exist.

### Manual Testing

Run the `__main__` blocks in each module:

```bash
# Test database layer
python ace_research/db.py

# Test XBRL ingestion
python ace_research/xbrl/ingest.py

# Test generator (requires data in DB)
python ace_research/experiments.py
```

### Test Data

The repository includes sample data in `sql_course/agent.db`. To inspect:

```bash
sqlite3 sql_course/agent.db

# List companies
SELECT DISTINCT company FROM financial_facts;

# List metrics
SELECT DISTINCT metric FROM financial_facts;

# Sample query
SELECT * FROM financial_facts WHERE company = 'Apple Inc.' LIMIT 10;
```

### Future Testing Recommendations

1. **Unit Tests** (pytest)
   - Test each database function
   - Test XBRL parsing with fixtures
   - Test confidence scoring edge cases

2. **Integration Tests**
   - End-to-end question answering
   - XBRL ingestion pipeline

3. **Regression Tests**
   - Known question-answer pairs
   - Benchmark against FINER dataset

---

## Common Tasks

### Task 1: Add Support for a New Company

```bash
# 1. Find CIK on SEC.gov
# 2. Ingest data
python -c "from ace_research.xbrl.ingest import ingest_company_10k_from_sec; \
ingest_company_10k_from_sec('0001318605', [2021, 2022, 2023], 'Tesla Inc.')"

# 3. Verify data
python sql_course/query_db.py "What is Tesla revenue in 2023?"
```

### Task 2: Debug a Failed Query

```python
# Enable debug mode (add to experiments.py)
import logging
logging.basicConfig(level=logging.DEBUG)

# Run query
gen = Generator()
result = gen.generate("Your failing question here")

# Check what the generator inferred
print("Inferred companies:", gen.infer_companies("Your question"))
print("Inferred metric:", gen.infer_metric("Your question"))
print("Inferred year:", gen.infer_year("Your question"))
```

### Task 3: Inspect Raw XBRL Data

```python
from ace_research.xbrl.ingest import get_company_cik, download_10k_ixbrl_file

# Download a filing
cik = "0000320193"
year = 2023
file_path = download_10k_ixbrl_file(cik, year)

print(f"Downloaded to: {file_path}")
# Open file_path in text editor to inspect XBRL tags
```

### Task 4: Clear Database and Re-ingest

```bash
# WARNING: This deletes all data!
sqlite3 sql_course/agent.db "DELETE FROM financial_facts;"

# Re-ingest
python -c "from ace_research.xbrl.ingest import ingest_company_10k_from_sec; \
ingest_company_10k_from_sec('0000320193', [2021, 2022, 2023], 'Apple Inc.')"
```

---

## Troubleshooting

### Problem: "ImportError: No module named 'ace_research'"

**Cause:** Python can't find the module.

**Solution:**

```bash
# Option 1: Add project root to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/sql_llm_project"

# Option 2: Use absolute imports
# Change: from db import ...
# To: from ace_research.db import ...

# Option 3: Install as editable package
pip install -e .
```

### Problem: "Arelle not found" or "No module named 'arelle'"

**Solution:**

```bash
pip install arelle
```

### Problem: "Database is locked"

**Cause:** SQLite only allows one writer at a time.

**Solution:**
- Close any open connections to the database
- Check for zombie processes: `ps aux | grep python`
- Use `conn.close()` after all queries

### Problem: "No facts extracted from XBRL filing"

**Possible causes:**
1. **Incorrect CIK format** → Ensure 10 digits with leading zeros
2. **No 10-K filing for that year** → Check SEC EDGAR manually
3. **Unmapped XBRL concepts** → Add to `XBRL_METRIC_MAP`

**Debug:**

```python
from ace_research.xbrl.ingest import extract_facts_from_ixbrl
facts = extract_facts_from_ixbrl("path/to/filing.htm")
print(f"Total facts extracted: {len(facts)}")
print(facts[:10])  # Inspect first 10 facts
```

### Problem: "Question returns None or empty result"

**Debug checklist:**

1. **Is the company in the database?**
   ```python
   from ace_research.db import get_available_companies
   print(get_available_companies())
   ```

2. **Is the metric available?**
   ```python
   from ace_research.db import get_available_metrics
   print(get_available_metrics())
   ```

3. **Is the year available?**
   ```python
   from ace_research.db import get_available_years
   print(get_available_years("Apple Inc."))
   ```

4. **Test the query directly:**
   ```python
   from ace_research.db import query_financial_fact
   value = query_financial_fact("revenue", 2023, "Apple Inc.")
   print(value)
   ```

---

## Contributing Guidelines

### Code Style

- Follow **PEP 8** style guide
- Use **type hints** for function signatures
- Add **docstrings** to all public functions
- Keep functions under 50 lines (prefer composition)

### Commit Messages

Use conventional commits format:

```
feat: Add support for quarterly data ingestion
fix: Handle division by zero in derived metrics
docs: Update API reference for new functions
refactor: Extract company inference to helper function
test: Add unit tests for confidence scoring
```

### Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make changes and test locally
3. Commit with descriptive messages
4. Push to your branch: `git push origin feature/your-feature-name`
5. Open a pull request with:
   - Clear description of changes
   - Link to related issues
   - Test results (when tests exist)

### Areas for Contribution

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for a prioritized list of enhancement opportunities.

**High-priority areas:**
- Add automated test suite
- Fix import path inconsistencies
- Add configuration management (environment variables)
- Implement logging infrastructure
- Add input validation and error handling
- Create API documentation
- Add performance optimizations

---

## Additional Resources

### External Documentation

- **SEC EDGAR**: https://www.sec.gov/edgar
- **XBRL Spec**: https://www.xbrl.org/Specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31+corrected-errata-2013-02-20.html
- **Arelle**: https://arelle.org/arelle/
- **SQLite**: https://www.sqlite.org/docs.html

### Research Papers

This project is inspired by:
- **FINER Benchmark**: Referenced in `ace_research/paper_notes.md`
- **ACE Framework**: Agentic Context Engineering pattern

### Contact

For questions or issues, please open an issue on GitHub or contact the maintainers.

---

**Happy coding! 🚀**
