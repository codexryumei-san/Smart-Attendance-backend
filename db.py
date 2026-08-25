import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# The blueprint translated strictly to PostgreSQL for Supabase
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('admin', 'lecturer')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    index_number VARCHAR(50) UNIQUE NOT NULL,
    programme VARCHAR(100) NOT NULL,
    group_name VARCHAR(100),
    level VARCHAR(50) NOT NULL DEFAULT '',
    biometric_consent INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL,
    encoding BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS group_courses (
    id SERIAL PRIMARY KEY,
    group_name VARCHAR(100) NOT NULL,
    course_name VARCHAR(100) NOT NULL,
    course_code VARCHAR(50) NOT NULL,
    UNIQUE (group_name, course_code)
);

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    group_course_id INTEGER NOT NULL,
    opened_by_user_id INTEGER,
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'expired')),
    FOREIGN KEY (group_course_id) REFERENCES group_courses (id),
    FOREIGN KEY (opened_by_user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    verification_mode VARCHAR(50) DEFAULT 'biometric',
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (session_id) REFERENCES sessions (id),
    FOREIGN KEY (student_id) REFERENCES students (id),
    UNIQUE (session_id, student_id)
);
"""

class PostgresConnection:
    def __init__(self, conn):
        self.conn = conn
        self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)

    def execute(self, query, params=None):
        self.cursor.execute(query, params)
        return self.cursor

    def commit(self):
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cursor.close()
        self.conn.close()

def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is missing from your .env file.")
    
    # Ensure the URL is formatted for psycopg2
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    conn = psycopg2.connect(database_url)
    return PostgresConnection(conn)

def init_db():
    with get_connection() as db:
        db.execute(SCHEMA)
        db.commit()