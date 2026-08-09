import numpy as np
from db import get_connection, init_db
from face_utils import encoding_to_blob

def add_test_student():
    """Add a test student with a dummy encoding for testing."""
    init_db()
    
    # Create a dummy 128-d encoding (all zeros for testing)
    dummy_encoding = np.zeros(128, dtype=np.float64)
    
    student_data = {
        "name": "Test Student",
        "index_number": "TEST/2024/001",
        "programme": "BSc Computer Science",
        "group_name": "Group A",
        "level": "Level 200",
        "biometric_consent": 1
    }
    
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO students (name, index_number, programme, group_name, level, biometric_consent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (student_data["name"], student_data["index_number"], student_data["programme"],
                 student_data["group_name"], student_data["level"], student_data["biometric_consent"])
            )
            student_id = cursor.lastrowid
            
            conn.execute(
                """
                INSERT INTO face_encodings (student_id, encoding)
                VALUES (?, ?)
                """,
                (student_id, encoding_to_blob(dummy_encoding))
            )
            conn.commit()
            
            print(f"Test student added successfully with ID: {student_id}")
            print(f"Name: {student_data['name']}")
            print(f"Index Number: {student_data['index_number']}")
            print(f"Group: {student_data['group_name']}")
            
        except Exception as e:
            print(f"Error adding test student: {e}")

if __name__ == "__main__":
    add_test_student()
