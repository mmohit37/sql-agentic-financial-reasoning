import sqlite3
import json
import os

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(script_dir, 'agent.db')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("=" * 80)
print("AGENT_PREDICTIONS")
print("=" * 80)
cur.execute("SELECT COUNT(*) FROM agent_predictions")
count = cur.fetchone()[0]
print(f"Total rows: {count}\n")

cur.execute("SELECT id, question, predicted_answer FROM agent_predictions LIMIT 10")
rows = cur.fetchall()
for row in rows:
    print(f"ID: {row[0]}")
    print(f"  Question: {row[1][:70]}")
    if row[2]:
        try:
            answer_dict = json.loads(row[2])
            print(f"  Answer: {answer_dict.get('answer', 'N/A')}")
            print(f"  Confidence: {answer_dict.get('confidence', 'N/A')}")
        except:
            print(f"  Answer: {row[2][:70]}")
    print()

print("\n" + "=" * 80)
print("AGENT_PLAYBOOK")
print("=" * 80)
cur.execute("SELECT COUNT(*) FROM agent_playbook")
count = cur.fetchone()[0]
print(f"Total rows: {count}\n")

cur.execute("SELECT id, rule FROM agent_playbook")
rows = cur.fetchall()
for row in rows:
    print(f"ID: {row[0]} | Rule: {row[1]}")

print("\n" + "=" * 80)
print("AGENT_FEEDBACK")
print("=" * 80)
cur.execute("SELECT COUNT(*) FROM agent_feedback")
count = cur.fetchone()[0]
print(f"Total rows: {count}\n")

cur.execute("SELECT prediction_id, correct_answer, is_correct FROM agent_feedback LIMIT 15")
rows = cur.fetchall()
for row in rows:
    print(f"Prediction ID: {row[0]} | Correct: {row[1]} | Is Correct: {row[2]}")

conn.close()

