# Exercise 0: The Setup

Installed SQLite3 (v3.46.x)
Verified with test.db
Set up Cursor workspace and PostgreSQL for later exercises

Notes:
- SQLite is used for learning syntax and small examples.
- PostgreSQL will be used later for multi-user performance comparison.
- Cursor will serve as my primary text editor instead of Notepad/IDE.



# Lesson 1 – Inserting and Reading Data

- Learned how to use `INSERT INTO` to add rows into a table.
- Practiced reading data with `SELECT *` and conditional queries.
- Verified that inserted data persists in the database.



# Lesson 2 – Multi-Table Database

- Created three tables: `person`, `pet`, and linking table `person_pet`.
- Learned that relation tables manage many-to-many relationships.
- Removing `person_pet` and putting pet info directly in `person` would make one-to-many relationships impossible (e.g., one person with multiple pets).
- Multiple rows in `person_pet` let one person link to many pets (e.g., “crazy cat lady” example).
- Read about SQLite datatypes: INTEGER, TEXT, REAL, BLOB, NULL.