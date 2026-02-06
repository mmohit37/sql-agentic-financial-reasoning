-- Migration: Add raw_xbrl_facts table
-- Purpose: Preserve ALL numeric XBRL facts before canonical reduction
-- Date: 2026-02-05

CREATE TABLE IF NOT EXISTS raw_xbrl_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- XBRL Concept Information
    concept_qname TEXT NOT NULL,          -- Full QName (namespace + local name)
    concept_local_name TEXT NOT NULL,     -- Just the local name (e.g., "Assets")
    concept_namespace TEXT,               -- Namespace URI

    -- Numeric Value & Unit
    numeric_value REAL NOT NULL,
    unit TEXT,                            -- e.g., "USD", "shares"

    -- Period Information
    period_type TEXT NOT NULL,            -- "instant" or "duration"
    start_date TEXT,                      -- ISO 8601 date for duration contexts
    end_date TEXT,                        -- ISO 8601 date (end for duration, date for instant)
    fiscal_year INTEGER,                  -- Inferred fiscal year

    -- Context & Dimensions
    context_id TEXT NOT NULL,             -- Original context ID from filing
    context_hash TEXT,                    -- Hash for deduplication
    dimensions TEXT,                      -- JSON: dimensional qualifiers (segments, scenarios)
    is_consolidated BOOLEAN DEFAULT 0,    -- True if no dimensional qualifiers

    -- Filing Metadata
    company TEXT NOT NULL,
    filing_source TEXT,                   -- URL or local file path
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes for common queries
    UNIQUE(company, filing_source, context_id, concept_local_name, numeric_value)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_raw_xbrl_company_year
    ON raw_xbrl_facts(company, fiscal_year);

CREATE INDEX IF NOT EXISTS idx_raw_xbrl_concept
    ON raw_xbrl_facts(concept_local_name);

CREATE INDEX IF NOT EXISTS idx_raw_xbrl_context_hash
    ON raw_xbrl_facts(context_hash);

CREATE INDEX IF NOT EXISTS idx_raw_xbrl_consolidated
    ON raw_xbrl_facts(is_consolidated, company, fiscal_year);

-- Comments explaining the table's purpose
--
-- This table stores ALL numeric XBRL facts from filings BEFORE canonical reduction.
--
-- Canonical reduction (selecting one value per company/year/metric) happens
-- DOWNSTREAM in the financial_facts table. This table preserves:
--   - All variants of similar concepts
--   - All dimensional slices (segments, scenarios)
--   - All period types (quarterly, annual, YTD, etc.)
--   - All contexts (both consolidated and segment-specific)
--
-- This enables:
--   1. Auditing canonical metric selection
--   2. Future re-mapping without re-downloading filings
--   3. Richer analysis using dimensional data
--   4. Debugging discrepancies in reported values
