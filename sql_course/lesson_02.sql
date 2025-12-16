CREATE TABLE person (
    id INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    age INTEGER
);

CREATE TABLE pet (
    id INTEGER PRIMARY KEY,
    name TEXT,
    breed TEXT,
    age INTEGER,
    DEAD INTEGER
);

CREATE TABLE person_pet (
    person_id INTEGER,
    pet_id INTEGER
);

CREATE TABLE cats (
    cat_id INTEGER PRIMARY KEY,
    name TEXT,
    age INTEGER,
    BREED TEXT,
    DEAD INTEGER
)