import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "database.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fullname TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'lecturer', 'course_rep')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    index_number TEXT NOT NULL UNIQUE,
    programme TEXT NOT NULL,
    group_name TEXT,
    level TEXT NOT NULL DEFAULT '',
    biometric_consent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    encoding BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS group_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL,
    course_name TEXT NOT NULL,
    course_code TEXT NOT NULL,
    UNIQUE (group_name, course_code)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_course_id INTEGER NOT NULL,
    opened_by_user_id INTEGER,
    opened_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'expired')),
    FOREIGN KEY (group_course_id) REFERENCES group_courses (id),
    FOREIGN KEY (opened_by_user_id) REFERENCES users (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_course_date
    ON sessions (group_course_id, date (opened_at));

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions (id),
    FOREIGN KEY (student_id) REFERENCES students (id),
    UNIQUE (session_id, student_id)
);
"""


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate_db():
    with get_connection() as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(students)").fetchall()
        }
        if columns and "level" not in columns:
            conn.execute(
                "ALTER TABLE students ADD COLUMN level TEXT NOT NULL DEFAULT ''"
            )
            conn.commit()
        
        # For SQLite, we need to recreate the table to change NOT NULL to NULL
        # Check if group_name is still NOT NULL by trying to insert NULL
        try:
            conn.execute("INSERT INTO students (name, index_number, programme, group_name, level, biometric_consent) VALUES ('_migration_test', '_test', '_test', NULL, '', 0)")
            conn.execute("DELETE FROM students WHERE index_number = '_test'")
            conn.commit()
        except sqlite3.IntegrityError:
            # group_name is still NOT NULL, need to migrate
            conn.execute("""
                CREATE TABLE students_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    index_number TEXT NOT NULL UNIQUE,
                    programme TEXT NOT NULL,
                    group_name TEXT,
                    level TEXT NOT NULL DEFAULT '',
                    biometric_consent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                INSERT INTO students_new (id, name, index_number, programme, group_name, level, biometric_consent, created_at)
                SELECT id, name, index_number, programme, group_name, level, biometric_consent, created_at FROM students
            """)
            conn.execute("DROP TABLE students")
            conn.execute("ALTER TABLE students_new RENAME TO students")
            conn.commit()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    migrate_db()
