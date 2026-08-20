import os
import time
import base64
import requests
import csv
from werkzeug.security import generate_password_hash, check_password_hash
from io import StringIO
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from db import get_connection, init_db

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173", "http://localhost:5174"])

# Fetch the Supabase URL from Render
database_url = os.getenv("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

with app.app_context():
    db.create_all()

init_db()

# --- Helper Function for Base64 ---
def clean_base64(b64_str):
    """Removes the data URI prefix from base64 strings so Face++ can read them."""
    if not b64_str: 
        return ""
    if "," in b64_str:
        return b64_str.split(",", 1)[-1]
    return b64_str

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Smart Attendance API is running via Face++"})

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
    group = str(group_raw).strip() if group_raw else None

    missing = [field for field, value in [("name", name), ("index_number", index_number), ("programme", programme), ("level", level)] if not value]
    if missing:
        return jsonify({"message": f"Missing required fields: {', '.join(missing)}"}), 400
    if not biometric_consent:
        return jsonify({"message": "Biometric consent is required to register a student."}), 400
    if not image_base64:
        return jsonify({"error": "A webcam photo is required to complete registration."}), 400

    # Clean the image and encode to bytes for database storage
    clean_image = clean_base64(image_base64)
    
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
            
            # Save the raw base64 string instead of a mathematical encoding
            conn.execute(
                """
                INSERT INTO face_encodings (student_id, encoding)
                VALUES (?, ?)
                """,
                (student_id, clean_image.encode('utf-8')),
            )
            conn.commit()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            return jsonify({"message": "A student with this index number already exists."}), 409
        return jsonify({"message": "Failed to register student."}), 500

    return jsonify({"message": "Student registered successfully.", "student": {"name": name}}), 201

@app.route("/api/recognize", methods=["POST"])
def recognize_face():
    data = request.get_json(silent=True) or {}
    image_base64 = data.get("image") or ""
    
    if not image_base64:
        return jsonify({"status": "error", "message": "No image provided"}), 400

    api_key = os.getenv('FACEPLUSPLUS_API_KEY')
    api_secret = os.getenv('FACEPLUSPLUS_API_SECRET')
    
    if not api_key or not api_secret:
        return jsonify({"status": "error", "message": "API keys are missing from Render environment."}), 500

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
                WHERE s.group_name = ?
                """, (group_name,)
            ).fetchall()

            if not students_data:
                return jsonify({"status": "no_students_in_group"}), 200

            # Loop through students and ask Face++ if the photo matches
            matched_student = None
            best_confidence = 0
            
            url = "https://api-us.faceplusplus.com/facepp/v3/compare"

            for student in students_data:
                # Decode the saved base64 string from the database
                try:
                    db_image_b64 = student["encoding"].decode('utf-8')
                except Exception:
                    continue # Skip old students registered before Face++ update

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
                    if conf > 80: # 80% is a confirmed match!
                        matched_student = student
                        break 
                
                # Sleep briefly to avoid Free Tier Face++ rate limits
                time.sleep(1.2)

            if not matched_student:
                return jsonify({"status": "no_match"}), 200

            # Check for duplicates
            existing = conn.execute(
                "SELECT id FROM attendance WHERE session_id = ? AND student_id = ?",
                (session_id, matched_student["id"])
            ).fetchone()
            
            if existing:
                return jsonify({"status": "duplicate", "student_name": matched_student["name"]}), 200
            
            # Record attendance
            conn.execute(
                "INSERT INTO attendance (session_id, student_id, verification_mode) VALUES (?, ?, 'biometric')",
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

# Keep the remaining routes exactly the same as your original file
@app.route("/api/courses", methods=["GET"])
def get_courses():
    with get_connection() as conn:
        courses = conn.execute("SELECT id, group_name, course_name, course_code FROM group_courses").fetchall()
    return jsonify([{"id": c["id"], "group_name": c["group_name"], "course_name": c["course_name"]} for c in courses])

@app.route('/api/sessions/start', methods=['POST'])
def start_session():
    data = request.json
    course_id = data.get('course_id')
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM sessions WHERE group_course_id = ? AND status = 'active'", (course_id,)).fetchone()
        if existing:
            return jsonify({"status": "success", "message": "Session reactivated"}), 200
        conn.execute("INSERT INTO sessions (group_course_id, status) VALUES (?, 'active')", (course_id,))
        conn.commit()
    return jsonify({"status": "success", "message": "New session started"}), 201

@app.route("/api/sessions/close", methods=["POST"])
def close_session():
    with get_connection() as conn:
        conn.execute("UPDATE sessions SET status = 'closed', closed_at = datetime('now') WHERE status = 'active'")
        conn.commit()
    return jsonify({"message": "Session closed"}), 200

@app.route("/api/sessions/active", methods=["GET"])
def get_active_session():
    with get_connection() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE status = 'active' ORDER BY opened_at DESC LIMIT 1").fetchone()
    return jsonify({"session": dict(session) if session else None}), 200

# ==========================================
# USER AUTHENTICATION ROUTES (Admin & Lecturer)
# ==========================================

@app.route("/api/register", methods=["POST"])
def register_user():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "lecturer").strip()

    if not all([name, email, password, role]):
        return jsonify({"error": "All fields are required."}), 400

    try:
        with get_connection() as conn:
            # Check if email already exists
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                return jsonify({"error": "This email is already registered."}), 409

            # Hash the password securely using werkzeug
            hashed_password = generate_password_hash(password)

            # Insert into the users table we created in Supabase
            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, hashed_password, role)
            )
            conn.commit()

        return jsonify({
            "success": True,
            "role": role,
            "message": "Account created successfully!"
        }), 201

    except Exception as exc:
        print(exc)
        return jsonify({"error": "Failed to create account. Please try again."}), 500


@app.route("/api/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    try:
        with get_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        # Verify user exists and password hash matches using werkzeug
        if user and check_password_hash(user["password_hash"], password):
            return jsonify({
                "success": True,
                "role": user["role"],
                "name": user["name"]
            }), 200
        else:
            return jsonify({"error": "Invalid email or password."}), 401

    except Exception as exc:
        print(exc)
        return jsonify({"error": "Login failed due to a server error."}), 500
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)