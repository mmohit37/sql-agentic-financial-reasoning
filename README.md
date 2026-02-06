# Financial Reasoning Agent (XBRL-powered)

This project implements an end-to-end **financial reasoning agent** that answers natural language questions about company financials using SEC XBRL data.  
It ingests raw SEC filings, normalizes financial facts, computes derived metrics, evaluates trends, compares companies, and returns answers with confidence scores and explanations.

The system is fully backend-driven and designed to be extensible for additional companies, metrics, or interfaces.

---

## Features

- SEC XBRL ingestion (inline XBRL via Arelle)
- Canonical financial fact normalization (deduplication across contexts)
- Derived metric computation (e.g., margins, ratios)
- Trend analysis over time
- Multi-company comparisons (winner / loser reasoning)
- Confidence scoring and explanation generation
- Self-evaluating agent loop with reflection and playbook updates
- SQLite-backed persistence for predictions, feedback, and metrics

---

SEC EDGAR (iXBRL)
10-K Filings
        |
        v
+-------------------------+
|  XBRL Ingestion Layer   |
|-------------------------|
| - Download filings      |
| - Parse via Arelle      |
| - Extract raw facts     |
| - Filter full-year data |
+-------------------------+
        |
        v
+------------------------------+
|  Canonical Normalization     |
|------------------------------|
| - Map XBRL concepts          |
| - Deduplicate facts          |
| - Select canonical values   |
| - Store by year/company     |
+------------------------------+
        |
        v
+------------------------------+
|  SQLite Fact Store           |
|------------------------------|
| - financial_facts            |
| - agent_predictions          |
| - agent_feedback             |
| - agent_playbook             |
+------------------------------+
        |
        v
+------------------------------+
|  Reasoning Engine            |
|------------------------------|
| - Metric inference           |
| - Trend analysis             |
| - Company comparison         |
| - Derived metrics            |
+------------------------------+
        |
        v
+------------------------------+
|  Confidence & Explanation    |
|------------------------------|
| - Confidence scoring         |
| - Explanation generation    |
| - Uncertainty handling      |
+------------------------------+
        |
        v
+------------------------------+
|  Agent Output                |
|------------------------------|
| - Structured answer          |
| - Confidence label           |
| - Explanation text           |
| - Stored feedback loop       |
+------------------------------+



## Supported Question Types

- **Single-value queries**
  - “What is *Company* net income for 20XX?”
- **Derived metrics**
  - “What is *Company* operating margin for 20XX?”
- **Trends**
  - “How has *Company* revenue changed over time?”
- **Multi-company comparisons**
  - “Compare *Company X* and *Company Y* revenue for 2022”
  - “Which company had higher net income in 2023, *Company X* or *Company Y*?”

All answers return:
- Final value or comparison
- Confidence score (0–1)
- Confidence label (high / medium / low)
- Explanation

---

## Tech Stack

- Python
- Arelle (XBRL parsing)
- SQLite
- SEC EDGAR API
- Structured agent loop (Generate → Reflect → Curate)
  
---

## Status

Backend complete.  
UI / frontend intentionally deferred for future expansion.
