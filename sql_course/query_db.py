"""
Database query utility for inspecting agent predictions, playbook, and feedback.

This script provides a formatted view of the agent database contents,
including predictions, learned rules, and feedback data.
"""

import sqlite3
import json
import os
from typing import Optional, List, Tuple, Any
from contextlib import contextmanager

# Configuration constants
DISPLAY_WIDTH = 80
QUESTION_TRUNCATE_LENGTH = 70
PREDICTIONS_LIMIT = 10
FEEDBACK_LIMIT = 15


@contextmanager
def get_db_connection(db_path: str):
    """
    Context manager for database connections.
    Ensures proper resource cleanup even if errors occur.
    
    Args:
        db_path: Path to the SQLite database file
        
    Yields:
        sqlite3.Connection: Database connection object
        
    Raises:
        sqlite3.Error: If database connection or operations fail
        FileNotFoundError: If database file doesn't exist
    """
    conn = None
    try:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        
        conn = sqlite3.connect(db_path)
        yield conn
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def execute_query(
    conn: sqlite3.Connection, 
    query: str, 
    params: Optional[Tuple[Any, ...]] = None
) -> List[Tuple[Any, ...]]:
    """
    Execute a SQL query and return all results.
    
    Args:
        conn: Database connection
        query: SQL query string
        params: Optional parameters for parameterized queries
        
    Returns:
        List of tuples containing query results
        
    Raises:
        sqlite3.Error: If query execution fails
    """
    try:
        cur = conn.cursor()
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        return cur.fetchall()
    except sqlite3.Error as e:
        print(f"Query execution error: {e}")
        print(f"Failed query: {query}")
        raise


def get_table_count(conn: sqlite3.Connection, table_name: str) -> int:
    """
    Get the total row count for a table.
    
    Args:
        conn: Database connection
        table_name: Name of the table to count
        
    Returns:
        Number of rows in the table
    """
    rows = execute_query(conn, f"SELECT COUNT(*) FROM {table_name}")
    return rows[0][0] if rows else "0"


def format_section_header(title: str) -> str:
    """Format a section header with consistent styling."""
    return f"\n{'=' * DISPLAY_WIDTH}\n{title}\n{'=' * DISPLAY_WIDTH}"


def parse_predicted_answer(answer_str: Optional[str]) -> dict:
    """
    Parse a predicted answer string, handling both JSON and plain text.
    
    Args:
        answer_str: The answer string (may be JSON or plain text)
        
    Returns:
        Dictionary with 'answer' and 'confidence' keys, or raw text
    """
    if not answer_str:
        return {'answer': 'N/A', 'confidence': 'N/A'}
    
    try:
        return json.loads(answer_str)
    except json.JSONDecodeError:
        # If not valid JSON, treat as plain text
        return {'answer': answer_str[:QUESTION_TRUNCATE_LENGTH], 'confidence': 'N/A'}


def display_agent_predictions(conn: sqlite3.Connection) -> None:
    """Display agent predictions with formatted output."""
    print(format_section_header("AGENT_PREDICTIONS"))
    
    count = get_table_count(conn, "agent_predictions")
    print(f"Total rows: {count}\n")
    
    query = "SELECT id, question, predicted_answer FROM agent_predictions LIMIT ?"
    rows = execute_query(conn, query, (PREDICTIONS_LIMIT,))
    
    for row in rows:
        pred_id, question, predicted_answer = row
        print(f"ID: {pred_id}")
        print(f"  Question: {question[:QUESTION_TRUNCATE_LENGTH]}")
        
        answer_data = parse_predicted_answer(predicted_answer)
        print(f"  Answer: {answer_data.get('answer', 'N/A')}")
        print(f"  Confidence: {answer_data.get('confidence', 'N/A')}")
        print()


def display_agent_playbook(conn: sqlite3.Connection) -> None:
    """Display agent playbook rules."""
    print(format_section_header("AGENT_PLAYBOOK"))
    
    count = get_table_count(conn, "agent_playbook")
    print(f"Total rows: {count}\n")
    
    rows = execute_query(conn, "SELECT id, rule FROM agent_playbook")
    
    for row in rows:
        rule_id, rule = row
        print(f"ID: {rule_id} | Rule: {rule}")


def display_agent_feedback(conn: sqlite3.Connection) -> None:
    """Display agent feedback data."""
    print(format_section_header("AGENT_FEEDBACK"))
    
    count = get_table_count(conn, "agent_feedback")
    print(f"Total rows: {count}\n")
    
    query = "SELECT prediction_id, correct_answer, is_correct FROM agent_feedback LIMIT ?"
    rows = execute_query(conn, query, (FEEDBACK_LIMIT,))
    
    for row in rows:
        prediction_id, correct_answer, is_correct = row
        print(f"Prediction ID: {prediction_id} | Correct: {correct_answer} | Is Correct: {is_correct}")


def main() -> None:
    """Main entry point for the script."""
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, 'agent.db')
    
    try:
        with get_db_connection(db_path) as conn:
            display_agent_predictions(conn)
            display_agent_playbook(conn)
            display_agent_feedback(conn)
    except (FileNotFoundError, sqlite3.Error) as e:
        print(f"Error: Failed to query database. {e}")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
