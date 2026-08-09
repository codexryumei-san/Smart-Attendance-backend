from db import get_connection, init_db

def seed_courses():
    """Seed sample courses for testing the kiosk interface."""
    init_db()
    
    courses = [
        ("Group A", "Introduction to Computer Science", "CS101"),
        ("Group A", "Data Structures and Algorithms", "CS201"),
        ("Group B", "Introduction to Computer Science", "CS101"),
        ("Group B", "Database Systems", "CS301"),
        ("Group A", "Software Engineering", "CS401"),
    ]
    
    with get_connection() as conn:
        for group_name, course_name, course_code in courses:
            try:
                conn.execute(
                    """
                    INSERT INTO group_courses (group_name, course_name, course_code)
                    VALUES (?, ?, ?)
                    """,
                    (group_name, course_name, course_code)
                )
                print(f"Added: {course_name} ({course_code}) - {group_name}")
            except Exception as e:
                print(f"Skipped (may exist): {course_name} ({course_code}) - {group_name}")
        
        conn.commit()
    
    print("\nCourses seeded successfully!")

if __name__ == "__main__":
    seed_courses()
