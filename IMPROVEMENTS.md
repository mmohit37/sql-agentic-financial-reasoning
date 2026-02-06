# Project Improvements Roadmap

This document outlines identified areas for improvement in the Financial Reasoning Agent project, prioritized by severity and impact.

---

## Critical Issues (Fix Immediately)

### 1. Import Path Inconsistency ⚠️

**Problem:** Mixed use of relative and absolute imports causes module resolution failures.

**Location:** `ace_research/experiments.py` vs `ace_research/xbrl/ingest.py`

**Current:**
```python
# experiments.py (line 1)
from db import query_financial_fact  # Relative import

# xbrl/ingest.py (line 10)
from ace_research.db import insert_financial_fact  # Absolute import
```

**Impact:**
- Works when run as script: `python experiments.py`
- Fails when imported as module: `from ace_research import experiments`
- Breaks IDE features (autocomplete, go-to-definition)

**Fix:**
```python
# Change all to absolute imports
from ace_research.db import query_financial_fact
```

**Effort:** Low (1-2 hours)

---

### 2. Hardcoded Relative Paths ⚠️

**Problem:** Database path is relative, causing failures when running from different directories.

**Location:** [ace_research/db.py:5](ace_research/db.py#L5)

**Current:**
```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "../sql_course/agent.db")
```

**Impact:**
- Breaks when current working directory changes
- Prevents packaging/distribution
- Hard to configure for different environments

**Fix:**
```python
# Option 1: Environment variable
DB_PATH = os.environ.get("FINANCIAL_AGENT_DB", "sql_course/agent.db")

# Option 2: Config file
import configparser
config = configparser.ConfigParser()
config.read('config.ini')
DB_PATH = config.get('database', 'path')

# Option 3: Relative to project root (with better detection)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "sql_course", "agent.db")
```

**Effort:** Low (2-3 hours including config setup)

---

### 3. Unclosed Database Connections 🐛

**Problem:** Database connections may not close on exception paths, causing resource leaks.

**Location:** Multiple functions in [ace_research/db.py](ace_research/db.py)

**Current:**
```python
def query_financial_fact(metric, year, company):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(...)  # If this fails, conn never closes
    row = cursor.fetchone()
    conn.close()  # Only reached if no exception
    return row[0] if row else None
```

**Fix:**
```python
def query_financial_fact(metric, year, company):
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(...)
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

# Or use context manager (better)
def query_financial_fact(metric, year, company):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(...)
        row = cursor.fetchone()
        return row[0] if row else None
```

**Effort:** Medium (4-6 hours to refactor all functions)

---

### 4. Missing SEC API Error Handling 🐛

**Problem:** No try-catch around HTTP requests, causing crashes on network failures.

**Location:** [ace_research/xbrl/ingest.py:34, 90](ace_research/xbrl/ingest.py#L34)

**Current:**
```python
response = requests.get(url, headers=SEC_HEADERS)
data = response.json()  # Crashes if response is not JSON
```

**Fix:**
```python
try:
    response = requests.get(url, headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()  # Raises HTTPError for 4xx/5xx
    data = response.json()
except requests.exceptions.RequestException as e:
    print(f"Error fetching {url}: {e}")
    return None
except json.JSONDecodeError:
    print(f"Invalid JSON response from {url}")
    return None
```

**Effort:** Medium (3-4 hours)

---

## High-Priority Issues (Plan Fixes)

### 5. No Automated Tests 🧪

**Problem:** Zero test coverage makes refactoring risky and regressions likely.

**Impact:**
- Can't confidently refactor code
- No regression detection
- Hard to validate bug fixes

**Recommendation:**

Create `tests/` directory with pytest:

```
tests/
├── test_db.py              # Database layer tests
├── test_xbrl_ingest.py     # XBRL parsing tests
├── test_generator.py       # Question answering tests
├── test_confidence.py      # Confidence scoring tests
└── fixtures/
    └── sample_10k.htm      # Mock XBRL filing
```

**Sample test:**
```python
# tests/test_db.py
import pytest
from ace_research.db import query_financial_fact, insert_financial_fact

def test_query_financial_fact(tmp_db):
    # Setup
    insert_financial_fact("Test Corp", 2023, "revenue", 1000000)

    # Test
    result = query_financial_fact("revenue", 2023, "Test Corp")

    # Assert
    assert result == 1000000
```

**Effort:** High (20-30 hours for comprehensive suite)

---

### 6. Missing Configuration Management ⚙️

**Problem:** No centralized configuration; values hardcoded throughout codebase.

**Current issues:**
- Email address exposed in source code ([xbrl/ingest.py:20](ace_research/xbrl/ingest.py#L20))
- Magic numbers (confidence penalties: 0.1, 0.3, 0.4)
- No environment-specific settings (dev/staging/prod)

**Recommendation:**

Create `config.py`:

```python
import os
from dataclasses import dataclass

@dataclass
class Config:
    # Database
    db_path: str = os.getenv("DB_PATH", "sql_course/agent.db")

    # SEC API
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "your-email@example.com")
    sec_base_url: str = "https://data.sec.gov"

    # Confidence scoring
    confidence_penalty_aggregation: float = 0.1
    confidence_penalty_derived: float = 0.3
    confidence_penalty_missing: float = 0.4
    confidence_floor: float = 0.2

    # Thresholds
    confidence_threshold_high: float = 0.8
    confidence_threshold_medium: float = 0.5

config = Config()
```

Use `.env` file (with `python-dotenv`):

```bash
# .env (not committed to git)
DB_PATH=sql_course/agent.db
SEC_USER_AGENT=your-email@example.com
```

**Effort:** Medium (6-8 hours)

---

### 7. No Logging Infrastructure 📝

**Problem:** Uses `print()` statements; can't control verbosity or output destination.

**Impact:**
- Can't disable debug output in production
- Can't log to files
- Hard to debug issues in deployed environments

**Recommendation:**

Add structured logging:

```python
import logging

# In each module
logger = logging.getLogger(__name__)

# Replace print()
# Before: print(f"Downloading filing for CIK {cik}")
# After: logger.info(f"Downloading filing for CIK {cik}")

# Configuration (in main entry point)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent.log'),
        logging.StreamHandler()
    ]
)
```

**Effort:** Low (3-4 hours)

---

### 8. Weak Canonical Fact Selection Logic 🤔

**Problem:** Uses `MAX(abs(value))` which can select wrong value.

**Location:** [ace_research/xbrl/ingest.py:127](ace_research/xbrl/ingest.py#L127), [ace_research/db.py:26](ace_research/db.py#L26)

**Example issue:**
```python
# Facts from XBRL
fact_a = -1000  # Loss (correct value)
fact_b = 500    # Partial/incorrect context

# Current logic
canonical = max([fact_a, fact_b], key=lambda x: abs(x))
# Returns: -1000 ✓ (correct by luck)

# But for:
fact_a = -100   # Small loss (correct)
fact_b = 500    # Wrong context
canonical = max([fact_a, fact_b], key=lambda x: abs(x))
# Returns: 500 ✗ (wrong!)
```

**Better approach:**

```python
# 1. Prioritize by context reliability
def select_canonical_fact(facts):
    # Prefer: consolidated > parent > segment
    # Prefer: annual > quarterly
    # Prefer: most recent filing date

    facts_sorted = sorted(facts, key=lambda f: (
        f['context_priority'],  # Consolidated = 1, Segment = 3
        f['filing_date']        # Most recent first
    ))
    return facts_sorted[0]['value']

# 2. Store all facts, expose aggregation options
def get_canonical_financial_fact(metric, year, company, method='max_abs'):
    if method == 'max_abs':
        return max(facts, key=lambda x: abs(x))
    elif method == 'most_recent':
        return facts_sorted_by_date[0]
    elif method == 'consolidated_only':
        return facts_filtered_by_context[0]
```

**Effort:** Medium (8-10 hours including testing)

---

### 9. Insufficient Input Validation 🛡️

**Problem:** No validation of user inputs or external data.

**Examples:**

```python
# No CIK validation
ingest_company_10k_from_sec("invalid", [2023], "Test")
# Should validate: 10 digits, numeric

# No year validation
query_financial_fact("revenue", 2100, "Apple")
# Should validate: reasonable year range (1990-current)

# No company name validation
query_financial_fact("revenue", 2023, "'; DROP TABLE financial_facts; --")
# Parameterized queries prevent SQL injection, but still should sanitize
```

**Recommendation:**

```python
def validate_cik(cik: str) -> bool:
    return cik.isdigit() and len(cik) == 10

def validate_year(year: int) -> bool:
    return 1990 <= year <= datetime.now().year + 1

def validate_metric(metric: str) -> bool:
    allowed_metrics = get_available_metrics() + list(derived_metrics.keys())
    return metric in allowed_metrics

# Use at function entry
def ingest_company_10k_from_sec(cik, years, company_name):
    if not validate_cik(cik):
        raise ValueError(f"Invalid CIK: {cik}")

    for year in years:
        if not validate_year(year):
            raise ValueError(f"Invalid year: {year}")

    # ... proceed with ingestion
```

**Effort:** Medium (5-6 hours)

---

### 10. No Rate Limiting for SEC API 🚦

**Problem:** Multiple rapid requests could trigger SEC throttling or IP ban.

**SEC guidelines:**
- No more than 10 requests per second
- Must include User-Agent header (already implemented)

**Recommendation:**

```python
import time
from functools import wraps

class RateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period  # in seconds
        self.calls = []

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            # Remove calls outside the period
            self.calls = [c for c in self.calls if now - c < self.period]

            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0])
                time.sleep(sleep_time)

            self.calls.append(time.time())
            return func(*args, **kwargs)
        return wrapper

# Usage
@RateLimiter(max_calls=10, period=1.0)  # 10 calls per second
def fetch_from_sec(url):
    return requests.get(url, headers=SEC_HEADERS)
```

**Effort:** Low (2-3 hours)

---

## Medium-Priority Issues (Refactor)

### 11. Code Duplication - Company Inference 🔄

**Problem:** Company name extraction logic is duplicated in multiple places.

**Locations:**
- [experiments.py:90](ace_research/experiments.py#L90)
- [experiments.py:144](ace_research/experiments.py#L144)
- [experiments.py:492](ace_research/experiments.py#L492)

**Fix:**

```python
def infer_companies(question: str) -> list[str]:
    """Extract company names from question text."""
    available_companies = get_available_companies()
    found = []

    for company in available_companies:
        # Case-insensitive search
        if company.lower() in question.lower():
            found.append(company)

    return found

# Use everywhere
companies = infer_companies(question)
```

**Effort:** Low (1-2 hours)

---

### 12. Dead Code - Orphaned Functions 🧹

**Problem:** Unused functions clutter codebase.

**Examples:**

1. **`format_comparison_answer()` in [generator.py](ace_research/generator.py)**
   - Never called in codebase
   - Similar logic exists in `experiments.py`
   - **Action:** Remove or document intended use

2. **`get_db_connection()` at line 490 in experiments.py**
   - Orphaned after refactor
   - **Action:** Remove

**Effort:** Low (1 hour)

---

### 13. Inconsistent Confidence Model 📊

**Problem:** Confidence penalties are arbitrary and lack documentation.

**Current penalties:**
- Aggregation: -0.1
- Derived metric: -0.3
- Missing components: -0.4

**Questions:**
- Why these specific values?
- How do they compose? (multiplicative vs additive)
- What about data freshness, source reliability?

**Recommendation:**

1. **Document assumptions:**
   ```python
   # Confidence Penalty Rationale:
   # - Aggregation (-0.1): Introduces rounding/precision loss
   # - Derived metric (-0.3): Propagates uncertainties from components
   # - Missing components (-0.4): Answer is incomplete
   # - Floor (0.2): Even low-confidence answers provide some value
   ```

2. **Consider probabilistic model:**
   ```python
   from dataclasses import dataclass

   @dataclass
   class ConfidenceFactors:
       data_quality: float = 1.0      # 0-1: Filing quality score
       data_freshness: float = 1.0    # Decay over time
       computation_complexity: float = 1.0  # Simple lookup = 1.0, derived = 0.7
       coverage: float = 1.0          # Fraction of required data present

   def compute_confidence(factors: ConfidenceFactors) -> float:
       # Multiplicative model
       return factors.data_quality * factors.data_freshness * \
              factors.computation_complexity * factors.coverage
   ```

**Effort:** High (10-15 hours including validation against ground truth)

---

### 14. Limited Trend Analysis 📈

**Problem:** Only detects strictly increasing/decreasing trends; misses patterns.

**Current logic:**
```python
if all(diff > 0 for diff in diffs):
    trend = "increasing"
elif all(diff < 0 for diff in diffs):
    trend = "decreasing"
else:
    trend = "mixed"
```

**Limitations:**
- Doesn't detect exponential growth
- Doesn't detect cyclical patterns
- Doesn't quantify trend strength
- No statistical significance

**Enhancement:**

```python
import numpy as np
from scipy import stats

def analyze_trend(years, values):
    # Linear regression
    slope, intercept, r_value, p_value, std_err = stats.linregress(years, values)

    # Classify
    if p_value < 0.05:  # Statistically significant
        if slope > 0:
            strength = "strong" if r_value**2 > 0.8 else "moderate"
            return f"{strength} increasing (R²={r_value**2:.2f})"
        else:
            strength = "strong" if r_value**2 > 0.8 else "moderate"
            return f"{strength} decreasing (R²={r_value**2:.2f})"
    else:
        return "no significant trend"

    # Could also detect:
    # - Exponential fit: values = a * e^(b*years)
    # - Polynomial fit: values = a*years^2 + b*years + c
    # - Cyclical patterns: FFT analysis
```

**Effort:** Medium (8-10 hours)

---

## Low-Priority Issues (Tech Debt)

### 15. Performance Optimizations 🚀

**Current inefficiencies:**

1. **Linear company search:** O(n) for company name matching
   ```python
   # Current
   for company in get_available_companies():  # N companies
       if company in question:
           return company

   # Better: Use trie or fuzzy matching
   from fuzzywuzzy import process
   company, score = process.extractOne(question, get_available_companies())
   ```

2. **No database indexes:**
   ```sql
   -- Add in schema
   CREATE INDEX idx_facts_lookup ON financial_facts(company, year, metric);
   CREATE INDEX idx_facts_company ON financial_facts(company);
   CREATE INDEX idx_facts_year ON financial_facts(year);
   ```

3. **Repeated database connections:**
   ```python
   # Current: Opens new connection for each query
   value1 = query_financial_fact("revenue", 2023, "Apple")
   value2 = query_financial_fact("net_income", 2023, "Apple")

   # Better: Connection pooling or pass connection
   with get_db_connection() as conn:
       value1 = query_financial_fact("revenue", 2023, "Apple", conn=conn)
       value2 = query_financial_fact("net_income", 2023, "Apple", conn=conn)
   ```

**Effort:** Medium (6-8 hours)

---

### 16. Missing Dependency Management 📦

**Problem:** No `requirements.txt` or `pyproject.toml`.

**Impact:**
- Hard for new developers to set up
- No version pinning (reproducibility issues)
- Can't use `pip install -e .`

**Recommendation:**

Create `requirements.txt`:
```
arelle>=2.3.0
requests>=2.28.0
python-dotenv>=1.0.0  # For config
pytest>=7.0.0         # For testing
```

Create `pyproject.toml` (modern Python packaging):
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "financial-reasoning-agent"
version = "0.1.0"
description = "SEC XBRL-powered financial reasoning agent"
requires-python = ">=3.10"
dependencies = [
    "arelle>=2.3.0",
    "requests>=2.28.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "black>=23.0.0",
    "flake8>=6.0.0",
]
```

**Effort:** Low (1-2 hours)

---

### 17. Security Improvements 🔒

**Issues:**

1. **Exposed email in source code:**
   ```python
   # Current (ingest.py:20)
   SEC_HEADERS = {
       "User-Agent": "your-email@example.com"
   }

   # Better
   SEC_HEADERS = {
       "User-Agent": os.getenv("SEC_USER_AGENT")
   }
   ```

2. **`eval()` usage (even if restricted):**
   ```python
   # Current (experiments.py)
   result = eval(formula, {"__builtins__": {}}, safelocals)

   # Better: Use ast.literal_eval or sympy
   import ast
   tree = ast.parse(formula, mode='eval')
   # Validate only allowed operations (Add, Sub, Mul, Div)
   result = safe_eval(tree, safelocals)
   ```

**Effort:** Low (2-3 hours)

---

### 18. Documentation Gaps 📚

**Missing:**

1. **API documentation** (docstrings incomplete)
2. **Installation guide** (no step-by-step setup)
3. **Usage examples** (no cookbook)
4. **Architecture diagrams** (README has ASCII, but could use images)
5. **Contribution guide** (no CONTRIBUTING.md)

**Recommendation:**

- Use Sphinx to generate API docs
- Add comprehensive docstrings following Google style
- Create CONTRIBUTING.md
- Add architecture diagram (draw.io or Mermaid)

**Effort:** High (15-20 hours)

---

## Summary Table

| Priority | Issue | Impact | Effort | Estimated Hours |
|----------|-------|--------|--------|-----------------|
| Critical | Import path inconsistency | High | Low | 1-2 |
| Critical | Hardcoded relative paths | High | Low | 2-3 |
| Critical | Unclosed DB connections | Medium | Medium | 4-6 |
| Critical | Missing SEC API error handling | Medium | Medium | 3-4 |
| High | No automated tests | High | High | 20-30 |
| High | Missing configuration management | Medium | Medium | 6-8 |
| High | No logging infrastructure | Medium | Low | 3-4 |
| High | Weak canonical fact selection | Medium | Medium | 8-10 |
| High | Insufficient input validation | Medium | Medium | 5-6 |
| High | No SEC API rate limiting | Low | Low | 2-3 |
| Medium | Code duplication | Low | Low | 1-2 |
| Medium | Dead code | Low | Low | 1 |
| Medium | Inconsistent confidence model | Medium | High | 10-15 |
| Medium | Limited trend analysis | Low | Medium | 8-10 |
| Low | Performance optimizations | Low | Medium | 6-8 |
| Low | Missing dependency management | Low | Low | 1-2 |
| Low | Security improvements | Low | Low | 2-3 |
| Low | Documentation gaps | Medium | High | 15-20 |

**Total estimated effort:** 100-140 hours

---

## Recommended Implementation Order

### Phase 1: Critical Fixes (2-3 days)
1. Fix import paths
2. Fix hardcoded paths (add config)
3. Add error handling for SEC API
4. Fix unclosed DB connections

### Phase 2: Infrastructure (1-2 weeks)
5. Add logging
6. Add input validation
7. Add rate limiting
8. Set up testing framework (pytest)

### Phase 3: Code Quality (1-2 weeks)
9. Write unit tests (aim for 70%+ coverage)
10. Remove dead code
11. Extract duplicated logic
12. Add dependency management

### Phase 4: Enhancements (2-3 weeks)
13. Improve canonical fact selection
14. Enhance trend analysis
15. Document confidence model
16. Performance optimizations

### Phase 5: Documentation (1 week)
17. Complete API documentation
18. Add usage examples
19. Create contribution guide
20. Add architecture diagrams

---

## Quick Wins (Start Here)

If you have limited time, focus on these high-impact, low-effort items:

1. ✅ Fix import paths (1-2 hours)
2. ✅ Add logging (3-4 hours)
3. ✅ Add `requirements.txt` (1 hour)
4. ✅ Remove dead code (1 hour)
5. ✅ Add input validation (5-6 hours)
6. ✅ Extract duplicate company inference logic (1-2 hours)

**Total: ~12-16 hours** for significant code quality improvement.

---

## Notes

- Some improvements are interdependent (e.g., tests require fixed imports)
- Prioritize based on your use case (production deployment vs research prototype)
- Consider using linters (flake8, pylint) and formatters (black) to catch issues early
- Set up pre-commit hooks to enforce code quality

---

**Last Updated:** 2026-01-23
