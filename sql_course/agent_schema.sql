-- Stores mock financial data
CREATE TABLE IF NOT EXISTS financial_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT,
    year INTEGER,
    metric TEXT,
    value REAL
);

-- Stores agent predictions
CREATE TABLE IF NOT EXISTS agent_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    predicted_answer TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Stores correctness
CREATE TABLE IF NOT EXISTS agent_feedback (
    prediction_id INTEGER,
    correct_answer TEXT,
    is_correct INTEGER,
    FOREIGN KEY (prediction_id) REFERENCES agent_predictions(id)

);

-- Stores learned rules
CREATE TABLE IF NOT EXISTS agent_playbook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule TEXT
);