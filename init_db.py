import sqlite3

def create_database():
    # Connect to database (creates it if it doesn't exist)
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()

    # 1. Create Users Table (Students & Reps)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        index_number TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL, -- 'student' or 'rep'
        programme TEXT NOT NULL,
        level TEXT NOT NULL,
        face_encoding BLOB -- This is where the AI math goes!
    )
    ''')

    # 2. Create Courses Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        course_code TEXT PRIMARY KEY,
        course_name TEXT NOT NULL,
        programme TEXT NOT NULL,
        level TEXT NOT NULL
    )
    ''')

    # 3. Create Attendance Logs Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        index_number TEXT NOT NULL,
        course_code TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL,
        FOREIGN KEY (index_number) REFERENCES users (index_number),
        FOREIGN KEY (course_code) REFERENCES courses (course_code)
    )
    ''')

    # Clear existing mock courses to avoid duplicates during testing
    cursor.execute('DELETE FROM courses')

    # Inject your default IT courses
    mock_courses = [
        ('INFT 401', 'Multimedia', 'BSc. Information Technology', '400'),
        ('INFT 402', 'Human Resource Development', 'BSc. Information Technology', '400'),
        ('INFT 403', 'System Security', 'BSc. Information Technology', '400')
    ]
    
    cursor.executemany('INSERT INTO courses VALUES (?, ?, ?, ?)', mock_courses)

    # Save and close
    conn.commit()
    conn.close()
    print("Database successfully created and populated with default courses!")

if __name__ == '__main__':
    create_database()