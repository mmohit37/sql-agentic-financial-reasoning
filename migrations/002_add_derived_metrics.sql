-- Migration: Add derived_metrics table
-- Purpose: Store computed metrics with explicit input provenance
-- Date: 2026-02-05

CREATE TABLE IF NOT EXISTS derived_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    company TEXT NOT NULL,
    year INTEGER NOT NULL,
    metric TEXT NOT NULL,          -- e.g., "roa_yoy_delta", "current_ratio"

    -- Computed value
    value REAL,                     -- NULL if computation failed

    -- Type classification
    metric_type TEXT NOT NULL,      -- "ratio", "delta", "single_year"

    -- Explicit input provenance (JSON)
    -- For ratios: {"numerator": "net_income", "denominator": "total_assets"}
    -- For deltas: {"current": "revenue", "prior": "revenue", "years": [2023, 2022]}
    -- For single-year: {"inputs": ["metric1", "metric2"]}
    input_components TEXT NOT NULL, -- JSON string

    -- Metadata
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Prevent duplicate computation
    UNIQUE(company, year, metric)
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_derived_company_year
    ON derived_metrics(company, year);

CREATE INDEX IF NOT EXISTS idx_derived_metric
    ON derived_metrics(metric);

CREATE INDEX IF NOT EXISTS idx_derived_type
    ON derived_metrics(metric_type);

-- Table Comments:
--
-- This table stores DERIVED financial metrics computed from canonical facts.
-- It is STRUCTURAL ONLY - no auto-computation.
--
-- Key properties:
-- 1. Explicit provenance: input_components records which canonical metrics were used
-- 2. Explicit failure: NULL value when computation fails (e.g., division by zero, missing input)
-- 3. No inference: missing data stays missing, never guessed
-- 4. Deterministic: same inputs always produce same output
--
-- Metric types:
-- - "ratio": numerator / denominator (e.g., ROA, current_ratio)
-- - "delta": t - (t-1) year-over-year change
-- - "single_year": computed from multiple inputs in same year
--
-- Example rows:
--
-- | company    | year | metric        | value  | metric_type  | input_components                                    |
-- |------------|------|---------------|--------|--------------|-----------------------------------------------------|
-- | Microsoft  | 2023 | roa           | 0.15   | ratio        | {"numerator": "net_income", "denominator": "total_assets"} |
-- | Microsoft  | 2023 | revenue_delta | 50000  | delta        | {"current": "revenue", "prior": "revenue", "years": [2023, 2022]} |
-- | Microsoft  | 2022 | current_ratio | NULL   | ratio        | {"numerator": "current_assets", "denominator": "current_liabilities"} |
--
-- The NULL in row 3 indicates computation failure (missing input or division by zero).
