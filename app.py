from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import numpy as np
import csv
from io import StringIO
import dlib
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Fetch the Supabase URL from Render
database_url = os.getenv("DATABASE_URL")

# SQLAlchemy requires 'postgresql://', but some cloud hosts provide 'postgres://'. This fixes it automatically.
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# Set the production database
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Ensure tables are created in Supabase when the app starts
with app.app_context():
    db.create_all()

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False

from db import get_connection, init_db
from face_utils import (
    decode_base64_image,
    encoding_to_blob,
    extract_face_encoding,
    check_liveness,
    blob_to_encoding,
)

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173", "http://localhost:5174"])

init_db()


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Smart Attendance API is running"})


@app.route("/api/register", methods=["POST"])
def register_student():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    index_number = (data.get("index_number") or "").strip()
    programme = (data.get("programme") or "").strip()
    level = (data.get("level") or "").strip()
    biometric_consent = bool(data.get("biometric_consent", False))
    image_base64 = data.get("image") or data.get("image_base64") or ""

    group_raw = data.get("group")
    if group_raw is None:
        group = None
    else:
        group = str(group_raw).strip() or None

    missing = [
        field
        for field, value in [
            ("name", name),
            ("index_number", index_number),
            ("programme", programme),
            ("level", level),
        ]
        if not value
    ]
    if missing:
        return jsonify({"message": f"Missing required fields: {', '.join(missing)}"}), 400

    if not biometric_consent:
        return jsonify({"message": "Biometric consent is required to register a student."}), 400

    if not image_base64:
        return jsonify({"error": "A webcam photo is required to complete registration."}), 400

    try:
        rgb_image = decode_base64_image(image_base64)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    encoding, face_error = extract_face_encoding(rgb_image)
    if face_error:
        return jsonify({"error": face_error}), 400

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO students (name, index_number, programme, group_name, level, biometric_consent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, index_number, programme, group, level, int(biometric_consent)),
            )
            student_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO face_encodings (student_id, encoding)
                VALUES (?, ?)
                """,
                (student_id, encoding_to_blob(encoding)),
            )
            conn.commit()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            return jsonify({"message": "A student with this index number already exists."}), 409
        return jsonify({"message": "Failed to register student."}), 500

    return jsonify(
        {
            "message": "Student registered successfully with biometric encoding.",
            "student": {
                "id": student_id,
                "name": name,
                "index_number": index_number,
                "programme": programme,
                "group": group,
                "level": level,
                "biometric_consent": biometric_consent,
            },
        }
    ), 201


@app.route("/api/courses", methods=["GET"])
def get_courses():
    """Get all available group courses for the kiosk interface."""
    with get_connection() as conn:
        courses = conn.execute(
            """
            SELECT id, group_name, course_name, course_code
            FROM group_courses
            ORDER BY group_name, course_name
            """
        ).fetchall()
    
    return jsonify([
        {
            "id": course["id"],
            "group_name": course["group_name"],
            "course_name": course["course_name"],
            "course_code": course["course_code"],
        }
        for course in courses
    ])


#@app.route("/api/sessions/start", methods=["POST"])

#def start_session():
 #   """Start a new attendance session for a specific group course."""
 #   data = request.get_json(silent=True) or {}
 #   group_course_id = data.get("group_course_id")
    
  #  if not group_course_id:
  #      return jsonify({"error": "group_course_id is required"}), 400
    
@app.route('/api/sessions/start', methods=['POST'])
def start_session():
    data = request.json
    course_id = data.get('course_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if a session already exists for this course
    existing_session = cursor.execute(
        "SELECT id, status FROM sessions WHERE course_id = ?", (course_id,)
    ).fetchone()
    
    if existing_session:
        # If it's already closed or active, re-activate/resume it instead of throwing a 409 error
        cursor.execute(
            "UPDATE sessions SET status = 'ACTIVE' WHERE course_id = ?", (course_id,)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Session reactivated/resumed"}), 200

    # Otherwise, create a brand new session
    cursor.execute(
        "INSERT INTO sessions (course_id, status) VALUES (?, 'ACTIVE')", (course_id,)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "New session started"}), 201
    
    try:
        with get_connection() as conn:
            # Check if a session for this course already exists today
            today = datetime.now().strftime("%Y-%m-%d")
            existing = conn.execute(
                """
                SELECT s.id, s.status, s.opened_at
                FROM sessions s
                WHERE s.group_course_id = ? AND date(s.opened_at) = ?
                """,
                (group_course_id, today)
            ).fetchone()
            
            if existing:
                return jsonify({
                    "error": "A session for this course already exists today.",
                    "existing_session": {
                        "id": existing["id"],
                        "status": existing["status"],
                        "opened_at": existing["opened_at"]
                    }
                }), 409
            
            # Check if there's already an active session (for any course)
            active_session = conn.execute(
                """
                SELECT s.id, s.group_course_id, gc.course_name, gc.group_name
                FROM sessions s
                JOIN group_courses gc ON s.group_course_id = gc.id
                WHERE s.status = 'active'
                """
            ).fetchone()
            
            if active_session:
                return jsonify({
                    "error": "An active session already exists.",
                    "active_session": {
                        "id": active_session["id"],
                        "course_name": active_session["course_name"],
                        "group_name": active_session["group_name"]
                    }
                }), 409
            
            # Create new session
            cursor = conn.execute(
                """
                INSERT INTO sessions (group_course_id, status)
                VALUES (?, 'active')
                """,
                (group_course_id,)
            )
            session_id = cursor.lastrowid
            conn.commit()
            
            # Get session details
            session = conn.execute(
                """
                SELECT s.id, s.group_course_id, s.opened_at, s.status,
                       gc.group_name, gc.course_name, gc.course_code
                FROM sessions s
                JOIN group_courses gc ON s.group_course_id = gc.id
                WHERE s.id = ?
                """,
                (session_id,)
            ).fetchone()
            
            return jsonify({
                "message": "Session started successfully",
                "session": {
                    "id": session["id"],
                    "group_course_id": session["group_course_id"],
                    "group_name": session["group_name"],
                    "course_name": session["course_name"],
                    "course_code": session["course_code"],
                    "opened_at": session["opened_at"],
                    "status": session["status"]
                }
            }), 201
            
    except Exception as exc:
        return jsonify({"error": f"Failed to start session: {str(exc)}"}), 500


@app.route("/api/sessions/close", methods=["POST"])
def close_session():
    """Close the currently active session."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    
    try:
        with get_connection() as conn:
            if session_id:
                # Close specific session
                conn.execute(
                    """
                    UPDATE sessions
                    SET status = 'closed', closed_at = datetime('now')
                    WHERE id = ? AND status = 'active'
                    """,
                    (session_id,)
                )
            else:
                # Close all active sessions
                conn.execute(
                    """
                    UPDATE sessions
                    SET status = 'closed', closed_at = datetime('now')
                    WHERE status = 'active'
                    """
                )
            
            conn.commit()
            return jsonify({"message": "Session closed successfully"}), 200
            
    except Exception as exc:
        return jsonify({"error": f"Failed to close session: {str(exc)}"}), 500


@app.route("/api/sessions/active", methods=["GET"])
def get_active_session():
    """Get the currently active session, auto-expiring if >4 hours old."""
    try:
        with get_connection() as conn:
            session = conn.execute(
                """
                SELECT s.id, s.group_course_id, s.opened_at, s.status,
                       gc.group_name, gc.course_name, gc.course_code
                FROM sessions s
                JOIN group_courses gc ON s.group_course_id = gc.id
                WHERE s.status = 'active'
                ORDER BY s.opened_at DESC
                LIMIT 1
                """
            ).fetchone()
            
            if not session:
                return jsonify({"session": None}), 200
            
            # Check if session has expired (>4 hours)
            opened_at = datetime.fromisoformat(session["opened_at"])
            now = datetime.now()
            hours_elapsed = (now - opened_at).total_seconds() / 3600
            
            if hours_elapsed >= 4:
                # Auto-expire the session
                conn.execute(
                    """
                    UPDATE sessions
                    SET status = 'expired', closed_at = datetime('now')
                    WHERE id = ?
                    """,
                    (session["id"],)
                )
                conn.commit()
                return jsonify({"session": None}), 200
            
            return jsonify({
                "session": {
                    "id": session["id"],
                    "group_course_id": session["group_course_id"],
                    "group_name": session["group_name"],
                    "course_name": session["course_name"],
                    "course_code": session["course_code"],
                    "opened_at": session["opened_at"],
                    "status": session["status"],
                    "hours_elapsed": hours_elapsed,
                    "time_remaining": 4 - hours_elapsed
                }
            }), 200
            
    except Exception as exc:
        return jsonify({"error": f"Failed to get active session: {str(exc)}"}), 500


@app.route("/api/recognize", methods=["POST"])
def recognize_face():
    """Process a frame for face recognition and attendance logging."""
    print("[RECOGNITION] New frame received")
    
    if not FACE_RECOGNITION_AVAILABLE:
        print("[RECOGNITION] ERROR: Face recognition library not available")
        return jsonify({"status": "error", "message": "Face recognition library not available. Please install required dependencies."}), 500
    
    data = request.get_json(silent=True) or {}
    image_base64 = data.get("image") or ""
    
    print(f"[RECOGNITION] Image data length: {len(image_base64)} characters")
    
    if not image_base64:
        print("[RECOGNITION] ERROR: No image provided")
        return jsonify({"status": "error", "message": "No image provided"}), 400
    
    try:
        # Check for active session
        print("[RECOGNITION] Checking for active session...")
        with get_connection() as conn:
            session = conn.execute(
                """
                SELECT s.id, s.group_course_id, s.status,
                       gc.group_name, gc.course_name
                FROM sessions s
                JOIN group_courses gc ON s.group_course_id = gc.id
                WHERE s.status = 'active'
                ORDER BY s.opened_at DESC
                LIMIT 1
                """
            ).fetchone()
            
            if not session:
                print("[RECOGNITION] No active session found")
                return jsonify({"status": "no_active_session"}), 200
            
            session_id = session["id"]
            group_name = session["group_name"]
            print(f"[RECOGNITION] Active session found: {session_id}, group: {group_name}")
        
        # Decode image
        print("[RECOGNITION] Decoding image...")
        rgb_image = decode_base64_image(image_base64)
        print(f"[RECOGNITION] Image decoded successfully, shape: {rgb_image.shape}")
        
        # Wrap detection and matching logic in try-except for error handling
        try:
            # Detect faces using HOG model
            print("[RECOGNITION] Detecting faces with HOG model...")
            face_locations = face_recognition.face_locations(rgb_image, model="hog")
            face_count = len(face_locations)
            print(f"[RECOGNITION] Faces detected: {face_count}")
            
            if face_count == 0:
                print("[RECOGNITION] No faces detected")
                return jsonify({"status": "no_face_detected"}), 200
            
            if face_count > 1:
                print("[RECOGNITION] Multiple faces detected")
                return jsonify({"status": "multiple_faces_detected"}), 200
            
            # Check liveness
            face_location = face_locations[0]
            print("[RECOGNITION] Checking liveness...")
            is_live, liveness_error = check_liveness(face_location, rgb_image)
            if not is_live:
                print(f"[RECOGNITION] Liveness check failed: {liveness_error}")
                return jsonify({"status": "spoof_detected", "message": liveness_error}), 200
            
            print("[RECOGNITION] Liveness check passed")
            
            # Extract encoding
            print("[RECOGNITION] Extracting face encoding...")
            encodings = face_recognition.face_encodings(rgb_image, face_locations)
            if not encodings:
                print("[RECOGNITION] Failed to extract encoding")
                return jsonify({"status": "encoding_failed"}), 200
            
            unknown_encoding = encodings[0]
            print("[RECOGNITION] Encoding extracted successfully")
            
            # Query only students from the active session's group (FR-4)
            print(f"[RECOGNITION] Querying students for group: {group_name}")
            with get_connection() as conn:
                students_data = conn.execute(
                    """
                    SELECT s.id, s.name, s.index_number, fe.encoding
                    FROM students s
                    JOIN face_encodings fe ON s.id = fe.student_id
                    WHERE s.group_name = ?
                    """,
                    (group_name,)
                ).fetchall()
            
            print(f"[RECOGNITION] Found {len(students_data)} students in group")
            
            if not students_data:
                print("[RECOGNITION] No students found in group")
                return jsonify({"status": "no_students_in_group"}), 200
            
            # Prepare known encodings
            known_encodings = []
            student_info = []
            
            for student in students_data:
                encoding = blob_to_encoding(student["encoding"])
                known_encodings.append(encoding)
                student_info.append({
                    "id": student["id"],
                    "name": student["name"],
                    "index_number": student["index_number"]
                })
            
            print(f"[RECOGNITION] Prepared {len(known_encodings)} known encodings")
            
            # Find best match using face_distance with 0.6 threshold
            print("[RECOGNITION] Computing face distances...")
            distances = face_recognition.face_distance(known_encodings, unknown_encoding)
            best_match_index = np.argmin(distances)
            best_distance = distances[best_match_index]
            print(f"[RECOGNITION] Best match distance: {best_distance:.4f}")
            
            if best_distance > 0.6:
                print(f"[RECOGNITION] No match found (distance {best_distance:.4f} > 0.6)")
                return jsonify({"status": "no_match"}), 200
            
            matched_student = student_info[best_match_index]
            print(f"[RECOGNITION] Match found: {matched_student['name']} (distance: {best_distance:.4f})")
            
            # Check for duplicate attendance (FR-6)
            print(f"[RECOGNITION] Checking for duplicate attendance for student {matched_student['id']}...")
            with get_connection() as conn:
                existing = conn.execute(
                    """
                    SELECT id FROM attendance
                    WHERE session_id = ? AND student_id = ?
                    """,
                    (session_id, matched_student["id"])
                ).fetchone()
                
                if existing:
                    print(f"[RECOGNITION] Duplicate attendance detected for {matched_student['name']}")
                    return jsonify({
                        "status": "duplicate",
                        "student_name": matched_student["name"],
                        "student_id": matched_student["id"]
                    }), 200
                
                # Insert new attendance record (FR-5)
                print(f"[RECOGNITION] Recording attendance for {matched_student['name']}...")
                conn.execute(
                    """
                    INSERT INTO attendance (session_id, student_id, verification_mode)
                    VALUES (?, ?, 'biometric')
                    """,
                    (session_id, matched_student["id"])
                )
                conn.commit()
                print(f"[RECOGNITION] Attendance recorded successfully")
            
            return jsonify({
                "status": "success",
                "student_name": matched_student["name"],
                "student_id": matched_student["id"],
                "index_number": matched_student["index_number"],
                "confidence": float(1 - best_distance)
            }), 200
            
        except Exception as exc:
            print(f"[RECOGNITION] Error during detection/matching: {str(exc)}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Detection/matching error: {str(exc)}"}), 500
        
    except ValueError as exc:
        print(f"[RECOGNITION] ValueError: {str(exc)}")
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        print(f"[RECOGNITION] Unexpected error: {str(exc)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/reports/attendance", methods=["GET"])
def get_attendance_report():
    """Get attendance report with optional filters for course, date, and group."""
    course_id = request.args.get("course_id")
    date_filter = request.args.get("date")
    group_filter = request.args.get("group")
    
    try:
        with get_connection() as conn:
            # Build the base query
            query = """
                SELECT 
                    s.id as student_id,
                    s.name,
                    s.index_number,
                    s.programme,
                    s.group_name,
                    a.id as attendance_id,
                    a.session_id,
                    a.recorded_at,
                    a.verification_mode,
                    a.override_reason,
                    gc.course_name,
                    gc.course_code,
                    ses.opened_at as session_date
                FROM students s
                LEFT JOIN attendance a ON s.id = a.student_id
                LEFT JOIN sessions ses ON a.session_id = ses.id
                LEFT JOIN group_courses gc ON ses.group_course_id = gc.id
                WHERE 1=1
            """
            params = []
            
            # Apply filters
            if course_id:
                query += " AND ses.group_course_id = ?"
                params.append(course_id)
            
            if group_filter:
                query += " AND s.group_name = ?"
                params.append(group_filter)
            
            if date_filter:
                query += " AND date(ses.opened_at) = ?"
                params.append(date_filter)
            
            query += " ORDER BY s.group_name, s.name"
            
            students = conn.execute(query, params).fetchall()
            
            # Format the response
            report = []
            for student in students:
                if student["attendance_id"]:
                    status = "Present"
                    time_logged = student["recorded_at"]
                    verification_mode = student["verification_mode"] or "biometric"
                    override_reason = student["override_reason"]
                else:
                    status = "Absent"
                    time_logged = None
                    verification_mode = None
                    override_reason = None
                
                report.append({
                    "student_id": student["student_id"],
                    "name": student["name"],
                    "index_number": student["index_number"],
                    "programme": student["programme"],
                    "group": student["group_name"],
                    "course_name": student["course_name"],
                    "course_code": student["course_code"],
                    "status": status,
                    "time_logged": time_logged,
                    "verification_mode": verification_mode,
                    "override_reason": override_reason,
                    "session_date": student["session_date"]
                })
            
            return jsonify({"report": report}), 200
            
    except Exception as exc:
        print(f"[REPORTS] Error generating attendance report: {str(exc)}")
        return jsonify({"error": f"Failed to generate report: {str(exc)}"}), 500


@app.route("/api/attendance/override", methods=["POST"])
def override_attendance():
    """Manually override attendance record for a student."""
    data = request.get_json(silent=True) or {}
    
    session_id = data.get("session_id")
    student_id = data.get("student_id")
    action = data.get("action")  # "mark_present" or "mark_absent"
    override_reason = data.get("override_reason")
    course_id = data.get("course_id")  # Optional: used to find session if not provided
    
    if not student_id or not action:
        return jsonify({"error": "student_id and action are required"}), 400
    
    if action == "mark_present" and not override_reason:
        return jsonify({"error": "override_reason is required when marking present"}), 400
    
    try:
        with get_connection() as conn:
            # If session_id not provided, try to find the most recent session for the course
            if not session_id and course_id:
                session = conn.execute(
                    """
                    SELECT id FROM sessions
                    WHERE group_course_id = ?
                    ORDER BY opened_at DESC
                    LIMIT 1
                    """,
                    (course_id,)
                ).fetchone()
                if session:
                    session_id = session["id"]
            
            if action == "mark_present":
                if not session_id:
                    return jsonify({"error": "session_id or course_id is required to mark present"}), 400
                
                # Check if attendance record already exists
                existing = conn.execute(
                    """
                    SELECT id FROM attendance
                    WHERE session_id = ? AND student_id = ?
                    """,
                    (session_id, student_id)
                ).fetchone()
                
                if existing:
                    # Update existing record
                    conn.execute(
                        """
                        UPDATE attendance
                        SET verification_mode = 'manual_override',
                            override_reason = ?,
                            recorded_at = datetime('now')
                        WHERE id = ?
                        """,
                        (override_reason, existing["id"])
                    )
                else:
                    # Create new attendance record
                    conn.execute(
                        """
                        INSERT INTO attendance (session_id, student_id, verification_mode, override_reason)
                        VALUES (?, ?, 'manual_override', ?)
                        """,
                        (session_id, student_id, override_reason)
                    )
                conn.commit()
                return jsonify({"message": "Attendance marked as present with manual override"}), 200
            
            elif action == "mark_absent":
                if not session_id:
                    return jsonify({"error": "session_id is required to mark absent"}), 400
                
                # Delete the attendance record if it exists
                conn.execute(
                    """
                    DELETE FROM attendance
                    WHERE session_id = ? AND student_id = ?
                    """,
                    (session_id, student_id)
                )
                conn.commit()
                return jsonify({"message": "Attendance marked as absent"}), 200
            
            else:
                return jsonify({"error": "Invalid action. Use 'mark_present' or 'mark_absent'"}), 400
                
    except Exception as exc:
        print(f"[OVERRIDE] Error during attendance override: {str(exc)}")
        return jsonify({"error": f"Failed to override attendance: {str(exc)}"}), 500
    
    try:
        with get_connection() as conn:
            if action == "mark_present":
                # Check if attendance record already exists
                existing = conn.execute(
                    """
                    SELECT id FROM attendance
                    WHERE session_id = ? AND student_id = ?
                    """,
                    (session_id, student_id)
                ).fetchone()
                
                if existing:
                    # Update existing record
                    conn.execute(
                        """
                        UPDATE attendance
                        SET verification_mode = 'manual_override',
                            override_reason = ?,
                            recorded_at = datetime('now')
                        WHERE id = ?
                        """,
                        (override_reason, existing["id"])
                    )
                else:
                    # Create new attendance record
                    conn.execute(
                        """
                        INSERT INTO attendance (session_id, student_id, verification_mode, override_reason)
                        VALUES (?, ?, 'manual_override', ?)
                        """,
                        (session_id, student_id, override_reason)
                    )
                conn.commit()
                return jsonify({"message": "Attendance marked as present with manual override"}), 200
            
            elif action == "mark_absent":
                # Delete the attendance record if it exists
                conn.execute(
                    """
                    DELETE FROM attendance
                    WHERE session_id = ? AND student_id = ?
                    """,
                    (session_id, student_id)
                )
                conn.commit()
                return jsonify({"message": "Attendance marked as absent"}), 200
            
            else:
                return jsonify({"error": "Invalid action. Use 'mark_present' or 'mark_absent'"}), 400
                
    except Exception as exc:
        print(f"[OVERRIDE] Error during attendance override: {str(exc)}")
        return jsonify({"error": f"Failed to override attendance: {str(exc)}"}), 500


@app.route("/api/reports/export", methods=["GET"])
def export_attendance_csv():
    """Export attendance report as CSV file."""
    course_id = request.args.get("course_id")
    date_filter = request.args.get("date")
    group_filter = request.args.get("group")
    
    try:
        with get_connection() as conn:
            # Build the base query
            query = """
                SELECT 
                    s.id as student_id,
                    s.name,
                    s.index_number,
                    s.programme,
                    s.group_name,
                    a.session_id,
                    gc.course_name,
                    gc.course_code,
                    ses.opened_at as session_date,
                    a.recorded_at,
                    a.verification_mode,
                    a.override_reason
                FROM students s
                LEFT JOIN attendance a ON s.id = a.student_id
                LEFT JOIN sessions ses ON a.session_id = ses.id
                LEFT JOIN group_courses gc ON ses.group_course_id = gc.id
                WHERE 1=1
            """
            params = []
            
            # Apply filters
            if course_id:
                query += " AND ses.group_course_id = ?"
                params.append(course_id)
            
            if group_filter:
                query += " AND s.group_name = ?"
                params.append(group_filter)
            
            if date_filter:
                query += " AND date(ses.opened_at) = ?"
                params.append(date_filter)
            
            query += " ORDER BY s.group_name, s.name"
            
            students = conn.execute(query, params).fetchall()
            
            # Create CSV content
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                "Student ID",
                "Student Name",
                "Index Number",
                "Programme",
                "Group",
                "Course Name",
                "Course Code",
                "Session Date",
                "Time Logged",
                "Status",
                "Verification Mode",
                "Override Reason"
            ])
            
            # Write data rows
            for student in students:
                status = "Present" if student["recorded_at"] else "Absent"
                writer.writerow([
                    student["student_id"],
                    student["name"],
                    student["index_number"],
                    student["programme"],
                    student["group_name"],
                    student["course_name"] or "N/A",
                    student["course_code"] or "N/A",
                    student["session_date"] or "N/A",
                    student["recorded_at"] or "N/A",
                    status,
                    student["verification_mode"] or "N/A",
                    student["override_reason"] or "N/A"
                ])
            
            # Create response
            output.seek(0)
            csv_content = output.getvalue()
            
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={
                    "Content-Disposition": "attachment; filename=attendance_report.csv"
                }
            )
            
    except Exception as exc:
        print(f"[EXPORT] Error exporting CSV: {str(exc)}")
        return jsonify({"error": f"Failed to export CSV: {str(exc)}"}), 500


@app.route("/api/analytics/summary", methods=["GET"])
def get_analytics_summary():
    """Get high-level analytics summary."""
    try:
        with get_connection() as conn:
            # Total registered students
            total_students = conn.execute(
                "SELECT COUNT(*) as count FROM students"
            ).fetchone()["count"]
            
            # Total active sessions (today)
            today = datetime.now().strftime("%Y-%m-%d")
            active_sessions = conn.execute(
                """
                SELECT COUNT(*) as count FROM sessions
                WHERE date(opened_at) = ? AND status = 'active'
                """,
                (today,)
            ).fetchone()["count"]
            
            # Average attendance rate (last 7 days)
            avg_attendance = conn.execute(
                """
                SELECT 
                    COALESCE(AVG(attendance_rate), 0) as rate
                FROM (
                    SELECT 
                        session_id,
                        COUNT(DISTINCT student_id) * 100.0 / 
                        (SELECT COUNT(*) FROM students WHERE group_name = s.group_name) as attendance_rate
                    FROM attendance a
                    JOIN sessions ses ON a.session_id = ses.id
                    JOIN group_courses gc ON ses.group_course_id = gc.id
                    WHERE date(ses.opened_at) >= date('now', '-7 days')
                    GROUP BY session_id
                )
                """
            ).fetchone()["rate"]
            
            # Recent attendance logs (last 10)
            recent_logs = conn.execute(
                """
                SELECT 
                    s.name,
                    s.index_number,
                    gc.course_name,
                    a.recorded_at,
                    a.verification_mode
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                JOIN sessions ses ON a.session_id = ses.id
                JOIN group_courses gc ON ses.group_course_id = gc.id
                ORDER BY a.recorded_at DESC
                LIMIT 10
                """
            ).fetchall()
            
            recent_logs_formatted = [
                {
                    "name": log["name"],
                    "index_number": log["index_number"],
                    "course_name": log["course_name"],
                    "recorded_at": log["recorded_at"],
                    "verification_mode": log["verification_mode"]
                }
                for log in recent_logs
            ]
            
            return jsonify({
                "total_students": total_students,
                "active_sessions": active_sessions,
                "average_attendance_rate": round(avg_attendance, 2),
                "recent_logs": recent_logs_formatted
            }), 200
            
    except Exception as exc:
        print(f"[ANALYTICS] Error generating summary: {str(exc)}")
        return jsonify({"error": f"Failed to generate analytics: {str(exc)}"}), 500

# ==========================================
# PRESENTATION SAFETY: Global Error Handler
# ==========================================
@app.errorhandler(Exception)
def handle_exception(e):
    """
    Catches any fatal Python errors during the live presentation 
    and returns a clean JSON error instead of crashing the server.
    """
    # Log the error to the terminal for debugging
    print(f"CRITICAL ERROR AVERTED: {str(e)}")
    
    # Return a safe JSON response to the React frontend
    return jsonify({
        "status": "error",
        "message": "An unexpected server error occurred. Please try scanning again."
    }), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
