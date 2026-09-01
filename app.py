import os
import time
import requests
import cv2
import json
import numpy as np
from flask import Flask, request, jsonify, Response # <-- Make sure Response is here
# ... your other imports ...
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from dotenv import load_dotenv
from db import get_connection, init_db

load_dotenv()

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173", "http://localhost:5174", "http://172.20.10.4:5173", "http://172.20.10.4:5174"])

# Initialize live Supabase database
init_db()

def clean_base64(b64_str):
    if not b64_str: 
        return ""
    if "," in b64_str:
        return b64_str.split(",", 1)[-1]
    return b64_str

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Smart Attendance API is running on Supabase & Face++"})

# --- 1. STUDENT REGISTRATION (Dynamic Level Upgrade) ---
import base64
import numpy as np
import cv2
import json
import face_recognition

# --- 1. STUDENT REGISTRATION (Dynamic Level Upgrade) ---
@app.route("/api/register", methods=["POST"])
def register_student():
    data = request.get_json(silent=True) or {}

    # 1. Grab all fields first
    name = (data.get("name") or "").strip()
    index_number = (data.get("index_number") or "").strip()
    programme = (data.get("programme") or "").strip()
    level = (data.get("level") or "").strip()
    student_type = data.get('student_type', 'Regular (Morning)')
    admission_year = data.get("admission_year") 
    biometric_consent = bool(data.get("biometric_consent", False))
    image_base64 = data.get("image") or data.get("image_base64") or ""
    group_raw = data.get("group")
    group = str(group_raw).strip() if group_raw else None

    # 2. Validation
    missing = [field for field, value in [("name", name), ("index_number", index_number), ("programme", programme), ("admission_year", admission_year)] if not value]
    if missing:
        return jsonify({"message": f"Missing required fields: {', '.join(missing)}"}), 400
    if not biometric_consent:
        return jsonify({"message": "Biometric consent is required to register a student."}), 400
    if not image_base64:
        return jsonify({"error": "A webcam photo is required to complete registration."}), 400

    clean_image = clean_base64(image_base64)
    
    # 3. Process the image to get the face math
    try:
        # Turn the base64 string back into an image that face_recognition can read
        image_bytes = base64.b64decode(clean_image)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # ---> ADDED DEBUG LINE HERE <---
        cv2.imwrite("debug_test_image.jpg", img)
        
        rgb_image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        encodings = face_recognition.face_encodings(rgb_image)
        if len(encodings) == 0:
            return jsonify({"message": "No face detected in the image"}), 400
        
        # Grab the first face and convert its math array to a JSON string
        face_encoding_json = json.dumps(encodings[0].tolist())
        
    except Exception as e:
        print("🚨 IMAGE PROCESSING ERROR:", e)
        return jsonify({"message": "Invalid image format or processing error."}), 400

    # 4. Save to Database
    try:
        with get_connection() as conn:
            # STEP A: Save the student details
            cursor = conn.execute(
                """
                INSERT INTO students (name, index_number, programme, level, group_name, admission_year, biometric_consent, student_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (name, index_number, programme, level, group, int(admission_year), int(biometric_consent), student_type),
            )
            student_id = cursor.fetchone()["id"]
            
            # STEP B: Save the face encoding JSON exactly into your jsonb column
            conn.execute(
                """
                INSERT INTO face_encodings (student_id, index_number, encoding_data)
                VALUES (%s, %s, %s)
                """,
                (student_id, index_number, face_encoding_json),
            )
            conn.commit()
            
    except Exception as exc:
        print("🚨 REGISTRATION ERROR:", exc)
        if "unique constraint" in str(exc).lower():
            return jsonify({"message": "A student with this index number already exists."}), 409
        return jsonify({"message": "Failed to register student."}), 500
        
    return jsonify({"message": "Student registered successfully.", "student": {"name": name}}), 201


# --- PROGRAMME REPS ROUTES ---
@app.route("/api/course-reps", methods=["GET"])
def get_programme_reps():
    try:
        with get_connection() as conn:
            # Fetch all students who are flagged as reps
            query = """
                SELECT id, name, index_number, programme, level, group_name
                FROM students
                WHERE is_course_rep = TRUE
                ORDER BY programme ASC, level ASC, group_name ASC
            """
            reps = conn.execute(query).fetchall()
            return jsonify([dict(r) for r in reps]), 200
    except Exception as exc:
        print("Fetch reps error:", exc)
        return jsonify({"error": "Failed to fetch programme reps."}), 500


@app.route("/api/assign-rep", methods=["POST"])
def assign_programme_rep():
    data = request.json
    index_number = data.get("index_number")
    programme = data.get("programme")
    level = data.get("level")
    group = data.get("group", "")
    action = data.get("action", "promote")

    if not index_number:
        return jsonify({"error": "Student Index Number is required."}), 400

    try:
        with get_connection() as conn:
            # 1. Verify the student exists
            student = conn.execute(
                "SELECT id, name, programme, level, group_name FROM students WHERE index_number = %s", 
                (index_number,)
            ).fetchone()
            
            if not student:
                return jsonify({"error": f"No student found with Index Number: {index_number}"}), 404

            # 2. If promoting, verify they actually belong to the selected cohort
            if action == "promote":
                if student['programme'] != programme:
                    return jsonify({"error": f"Student is registered in {student['programme']}, not {programme}."}), 400
                if str(student['level']) != str(level):
                    return jsonify({"error": f"Student is in Level {student['level']}, not Level {level}."}), 400
                if programme == "BSc. Information Technology" and student['group_name'] != group:
                    return jsonify({"error": f"Student is in Group {student['group_name'] or 'None'}, not Group {group}."}), 400

            # 3. Update their rep status
            is_rep = True if action == "promote" else False
            
            conn.execute(
                "UPDATE students SET is_course_rep = %s WHERE id = %s", 
                (is_rep, student['id'])
            )
            conn.commit()  # <--- ADD THIS LINE! This permanently saves it to the database
            
            if is_rep:
                msg = f"Successfully promoted {student['name']} to rep for {programme}!"
            else:
                msg = f"Revoked rep status for {student['name']}."
                
            return jsonify({"message": msg}), 200
            
    except Exception as exc:
        print("Assign rep error:", exc)
        return jsonify({"error": "An error occurred while updating the student."}), 500


# --- 2. LIVE FACE VERIFICATION ENGINE ---
@app.route("/api/recognize", methods=["POST"])
def recognize_face():
    data = request.get_json(silent=True) or {}
    image_base64 = data.get("image") or ""
    
    if not image_base64:
        return jsonify({"status": "error", "message": "No image provided"}), 400

    api_key = os.getenv('FACEPLUSPLUS_API_KEY')
    api_secret = os.getenv('FACEPLUSPLUS_API_SECRET')
    
    if not api_key or not api_secret:
        return jsonify({"status": "error", "message": "API keys are missing."}), 500

    webcam_b64 = clean_base64(image_base64)

    try:
        with get_connection() as conn:
            session = conn.execute(
                """
                SELECT s.id, s.group_course_id, s.status, gc.group_name 
                FROM sessions s JOIN group_courses gc ON s.group_course_id = gc.id
                WHERE s.status = 'active' ORDER BY s.opened_at DESC LIMIT 1
                """
            ).fetchone()
            
            if not session:
                return jsonify({"status": "no_active_session"}), 200
            
            session_id = session["id"]
            group_name = session["group_name"]

            students_data = conn.execute(
                """
                SELECT s.id, s.name, s.index_number, fe.encoding
                FROM students s JOIN face_encodings fe ON s.id = fe.student_id
                WHERE s.group_name = %s
                """, (group_name,)
            ).fetchall()

            if not students_data:
                return jsonify({"status": "no_students_in_group"}), 200

            matched_student = None
            best_confidence = 0
            url = "https://api-us.faceplusplus.com/facepp/v3/compare"

            for student in students_data:
                try:
                    encoding_val = student["encoding"]
                    if isinstance(encoding_val, str):
                        db_image_b64 = encoding_val
                    else:
                        db_image_b64 = encoding_val.tobytes().decode('utf-8')
                except Exception:
                    continue 

                payload = {
                    'api_key': api_key,
                    'api_secret': api_secret,
                    'image_base64_1': db_image_b64,
                    'image_base64_2': webcam_b64
                }
                
                res = requests.post(url, data=payload)
                face_data = res.json()
                
                conf = face_data.get('confidence', 0)
                if conf > best_confidence:
                    best_confidence = conf
                    if conf > 80:
                        matched_student = student
                        break 
                
                time.sleep(1.2)

            if not matched_student:
                return jsonify({"status": "no_match"}), 200

            existing = conn.execute(
                "SELECT id FROM attendance WHERE session_id = %s AND student_id = %s",
                (session_id, matched_student["id"])
            ).fetchone()
            
            if existing:
                return jsonify({"status": "duplicate", "student_name": matched_student["name"]}), 200
            
            conn.execute(
                "INSERT INTO attendance (session_id, student_id, verification_mode) VALUES (%s, %s, 'biometric')",
                (session_id, matched_student["id"])
            )
            conn.commit()

            return jsonify({
                "status": "success",
                "student_name": matched_student["name"],
                "confidence": best_confidence
            }), 200

    except Exception as exc:
        print(exc)
        return jsonify({"status": "error", "message": "Detection failed."}), 500


# --- 3. COURSE MANAGEMENT ---
@app.route("/api/courses", methods=["POST"])
def add_course():
    data = request.json
    course_name = data.get("course_name")
    course_code = data.get("course_code")
    level = data.get("level")
    student_type = data.get("student_type", "Regular (Morning)")
    lecturer_id = data.get("lecturer_id")
    programmes = data.get("programmes", [])
    it_groups = data.get("it_groups", [])

    if not all([course_name, course_code, level, lecturer_id, programmes]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        with get_connection() as conn:
            # Loop through the selected programmes from the frontend
            for prog in programmes:
                # Special handling for IT students with groups
                if prog == "BSc. Information Technology" and it_groups:
                    for grp in it_groups:
                        # UPDATED: The conflict rule now checks course_code, programme, AND group_name!
                        conn.execute("""
                            INSERT INTO group_courses (course_code, course_name, level, student_type, programme, group_name, lecturer_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (course_code, programme, group_name) DO NOTHING
                        """, (course_code, course_name, level, student_type, prog, grp, lecturer_id))
                else:
                    # Standard insertion for all other programmes
                    # UPDATED: The conflict rule now checks course_code, programme, AND group_name!
                    conn.execute("""
                        INSERT INTO group_courses (course_code, course_name, level, student_type, programme, group_name, lecturer_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (course_code, programme, group_name) DO NOTHING
                    """, (course_code, course_name, level, student_type, prog, "Main", lecturer_id))
                    
            conn.commit()
            
        return jsonify({"message": "Courses generated and assigned successfully!"}), 201
        
    except Exception as exc:
        print(f"Error creating course: {exc}")
        return jsonify({"error": str(exc)}), 500


# --- 4. SESSION MANAGEMENT ---
@app.route('/api/sessions/start', methods=['POST'])
def start_session():
    data = request.json or {}
    course_id = data.get('course_id')
    if not course_id:
        return jsonify({"message": "Course ID is required."}), 400
        
    try:
        with get_connection() as conn:
            existing = conn.execute("SELECT id FROM sessions WHERE group_course_id = %s AND status = 'active'", (course_id,)).fetchone()
            if existing:
                return jsonify({"status": "success", "message": "Session reactivated"}), 200
            conn.execute("INSERT INTO sessions (group_course_id, status) VALUES (%s, 'active')", (course_id,))
            conn.commit()
        return jsonify({"status": "success", "message": "New session started"}), 201
    except Exception as exc:
        print("Session start error:", exc)
        return jsonify({"message": "Failed to start session."}), 500


@app.route("/api/sessions/close", methods=["POST"])
def close_session():
    with get_connection() as conn:
        conn.execute("UPDATE sessions SET status = 'closed', closed_at = NOW() WHERE status = 'active'")
        conn.commit()
    return jsonify({"message": "Session closed"}), 200


@app.route("/api/sessions/active", methods=["GET"])
def get_active_session():
    with get_connection() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE status = 'active' ORDER BY opened_at DESC LIMIT 1").fetchone()
    return jsonify({"session": dict(session) if session else None}), 200


# --- 5. ATTENDANCE LOGS ---
@app.route("/api/attendance", methods=["GET"])
def get_attendance_logs():
    search = request.args.get("search", "").strip()
    programme = request.args.get("programme", "").strip()
    level = request.args.get("level", "").strip()
    group = request.args.get("group", "").strip()
    
    try:
        with get_connection() as conn:
            query = """
                SELECT a.id, a.recorded_at, a.verification_mode, 
                       s.name as student_name, s.index_number, s.student_type, 
                       gc.course_name, gc.group_name, gc.course_code, gc.programme, gc.level
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                JOIN sessions sess ON a.session_id = sess.id
                JOIN group_courses gc ON sess.group_course_id = gc.id
                WHERE 1=1
            """
            params = []
            
            if search:
                query += " AND (gc.course_code ILIKE %s OR gc.course_name ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])
            if programme:
                query += " AND gc.programme = %s"
                params.append(programme)
            if level:
                query += " AND gc.level = %s"
                params.append(level)
            if group and programme == "BSc. Information Technology":
                query += " AND gc.group_name ILIKE %s"
                params.append(f"%{group}%")
                
            query += " ORDER BY a.recorded_at DESC LIMIT 200"
            logs = conn.execute(query, params).fetchall()
            
        return jsonify([dict(l) for l in logs]), 200
    except Exception as exc:
        print("Fetch attendance error:", exc)
        return jsonify({"error": "Failed to fetch attendance logs."}), 500


# --- 6. USERS & AUTHENTICATION ---
@app.route("/api/users", methods=["GET"])
def get_all_users():
    role = request.args.get("role")
    
    try:
        with get_connection() as conn:
            if role:
                users = conn.execute("SELECT id, name, email, role, created_at FROM users WHERE role = %s ORDER BY created_at DESC", (role,)).fetchall()
            else:
                users = conn.execute("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC").fetchall()
                
        return jsonify([dict(u) for u in users]), 200
    except Exception as exc:
        print("Fetch users error:", exc)
        return jsonify({"error": "Failed to fetch system users."}), 500


@app.route("/api/lecturers", methods=["GET"])
def get_lecturers():
    try:
        with get_connection() as conn:
            lecturers = conn.execute("SELECT id, name FROM users WHERE role = 'lecturer'").fetchall()
        return jsonify([dict(l) for l in lecturers]), 200
    except Exception as exc:
        print("Error fetching lecturers:", exc)
        return jsonify({"error": "Failed to fetch lecturers"}), 500


@app.route("/api/auth/register", methods=["POST"])
def register_user():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    role = data.get("role", "").strip()

    if not all([name, email, password, role]):
        return jsonify({"error": "All fields are required."}), 400

    try:
        with get_connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
            if existing:
                return jsonify({"error": "This email is already registered."}), 409

            hashed_password = generate_password_hash(password)

            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
                """,
                (name, email, hashed_password, role)
            )
            conn.commit()

        return jsonify({"success": True, "role": role, "message": "Account created successfully!"}), 201

    except Exception as exc:
        print("Registration Error:", exc)
        return jsonify({"error": "Failed to create account."}), 500


@app.route("/api/auth/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    try:
        with get_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            return jsonify({
                "success": True, 
                "role": user["role"], 
                "name": user["name"],
                "email": user["email"] 
            }), 200
        else:
            return jsonify({"error": "Invalid email or password."}), 401

    except Exception as exc:
        print("Login Error:", exc)
        return jsonify({"error": "Login failed."}), 500


# --- 7. DASHBOARD METRICS ---
@app.route("/api/dashboard/stats", methods=["GET"])
def get_dashboard_stats():
    try:
        with get_connection() as conn:
            student_res = conn.execute("SELECT COUNT(*) as count FROM students").fetchone()
            course_res = conn.execute("SELECT COUNT(*) as count FROM group_courses").fetchone()
            attendance_res = conn.execute(
                "SELECT COUNT(*) as count FROM attendance WHERE DATE(recorded_at) = CURRENT_DATE"
            ).fetchone()
            
            active_session = conn.execute(
                """
                SELECT s.id, gc.course_name, gc.course_code, gc.group_name, s.opened_at
                FROM sessions s 
                JOIN group_courses gc ON s.group_course_id = gc.id 
                WHERE s.status = 'active' 
                ORDER BY s.opened_at DESC LIMIT 1
                """
            ).fetchone()

            return jsonify({
                "students_count": student_res["count"] if student_res else 0,
                "courses_count": course_res["count"] if course_res else 0,
                "today_attendance": attendance_res["count"] if attendance_res else 0,
                "active_session": dict(active_session) if active_session else None
            }), 200
    except Exception as exc:
        print("Dashboard stats error:", exc)
        return jsonify({"error": "Failed to fetch dashboard metrics."}), 500


# --- 8. ADMIN CRUD: STUDENTS ---
@app.route("/api/students", methods=["GET"])
def get_all_students():
    try:
        with get_connection() as conn:
            # Added is_course_rep right here!
            students = conn.execute("SELECT id, name, index_number, programme, level, group_name, admission_year, is_course_rep FROM students ORDER BY name ASC").fetchall()
        return jsonify([dict(s) for s in students]), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/api/students/<int:student_id>", methods=["PUT"])
def update_student(student_id):
    data = request.get_json()
    try:
        with get_connection() as conn:
            conn.execute("""
                UPDATE students 
                SET name=%s, index_number=%s, programme=%s, level=%s, group_name=%s 
                WHERE id=%s
            """, (data.get("name"), data.get("index_number"), data.get("programme"), data.get("level"), data.get("group_name"), student_id))
            conn.commit()
        return jsonify({"success": True, "message": "Student updated successfully!"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/api/students/<int:student_id>", methods=["DELETE"])
def delete_student(student_id):
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM students WHERE id=%s", (student_id,))
            conn.commit()
        return jsonify({"success": True, "message": "Student deleted successfully!"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# --- 9. ADMIN CRUD: COURSES ---
@app.route("/api/courses", methods=["GET"])
def get_all_courses():
    try:
        with get_connection() as conn:
            courses = conn.execute("""
                SELECT c.id, c.course_name, c.course_code, c.programme, c.group_name, c.level, c.student_type, u.name as lecturer_name 
                FROM group_courses c 
                LEFT JOIN users u ON c.lecturer_id = u.id
            """).fetchall()
        return jsonify([dict(c) for c in courses]), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/api/courses/<int:course_id>", methods=["PUT"])
def update_course(course_id):
    data = request.get_json()
    try:
        with get_connection() as conn:
            conn.execute("""
                UPDATE group_courses 
                SET course_name=%s, course_code=%s, programme=%s, level=%s 
                WHERE id=%s
            """, (data.get("course_name"), data.get("course_code"), data.get("programme"), data.get("level"), course_id))
            conn.commit()
        return jsonify({"success": True, "message": "Course updated successfully!"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/api/courses/<int:course_id>", methods=["DELETE"])
def delete_course(course_id):
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM group_courses WHERE id=%s", (course_id,))
            conn.commit()
        return jsonify({"success": True, "message": "Course deleted successfully!"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ==========================================
# KIOSK LIVE VIDEO STREAMING & FACE DETECTION
# ==========================================

# Initialize the webcam
camera = cv2.VideoCapture(0)
# Load OpenCV's built-in face detection classifier (no extra downloads needed!)
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # 1. Flip the frame horizontally for a natural mirror view
            frame = cv2.flip(frame, 1)
            
            # 2. Convert to grayscale for faster face detection processing
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 3. Detect faces in the frame
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            
            # 4. Draw interactive targeting boxes around detected faces
            for (x, y, w, h) in faces:
                # Draw main bounding box (Emerald/Green color to match your UI)
                color = (16, 185, 129) # BGR format for emerald
                cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                
                # Draw targeting corner accents
                cv2.putText(frame, "Target Acquired", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # 5. Compress the processed frame into JPEG format
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            # Yield the frame continuously to the browser stream
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/api/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)