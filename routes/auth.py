from flask import Blueprint, request, jsonify, current_app
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
import random
from .verify_email import send_code_to_email

auth_bp = Blueprint('auth', __name__)
print("auth.py is being imported")

def get_db():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

# ✅ Register Route
@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        return jsonify({'error': 'User already exists'}), 409

    hashed_pw = generate_password_hash(password)
    cursor.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed_pw))
    conn.commit()

    send_code_to_email(email)
    conn.close()

    return jsonify({'message': 'User registered. Verification code sent.'}), 201

# ✅ Login Route
@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not check_password_hash(user['password'], password):
        return jsonify({'error': 'Incorrect password'}), 401

    if user['is_verified'] == 0:
        return jsonify({'error': 'Please verify your email before logging in.'}), 403

    token = jwt.encode({
        'sub': str(user['id']),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, current_app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({'token': token}), 200

# ✅ Send Reset Code
@auth_bp.route('/send-reset-code', methods=['POST'])
def send_reset_code():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email is required'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    if not cursor.fetchone():
        return jsonify({'error': 'User not found'}), 404

    code = str(random.randint(100000, 999999))
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat()

    cursor.execute(
        "INSERT OR REPLACE INTO password_reset_codes (email, code, expires_at) VALUES (?, ?, ?)",
        (email, code, expires_at)
    )
    conn.commit()
    conn.close()

    send_code_to_email(email)

    return jsonify({'message': 'Reset code sent to your email'}), 200

# ✅ Verify Reset Code
@auth_bp.route('/verify-reset-code', methods=['POST'])
def verify_reset_code():
    data = request.get_json()
    email = data.get('email')
    code = data.get('code')

    if not email or not code:
        return jsonify({'error': 'Email and code are required'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT code, expires_at FROM password_reset_codes WHERE email = ?", (email,))
    row = cursor.fetchone()

    if not row:
        print(f"❌ No reset code found for {email}")
        return jsonify({'error': 'No code found'}), 404

    # 🔍 Debug: Show both expected and received codes
    expected_code = str(row['code']).strip()
    received_code = str(code).strip()
    print("🔍 Comparing codes:")
    print("Expected:", expected_code)
    print("Received:", received_code)

    if expected_code != received_code:
        print("❌ Mismatch: Incorrect code")
        return jsonify({'error': 'Incorrect code'}), 400

    print("⏰ Expiry time:", row['expires_at'])
    print("🕒 Now:", datetime.datetime.utcnow().isoformat())

    if datetime.datetime.fromisoformat(row['expires_at']) < datetime.datetime.utcnow():
        return jsonify({'error': 'Code expired'}), 400

    return jsonify({'message': 'Code verified'}), 200


# ✅ Reset Password
@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    email = data.get('email')
    new_password = data.get('password')

    if not email or not new_password:
        return jsonify({'error': 'Email and new password are required'}), 400

    hashed_pw = generate_password_hash(new_password)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password = ? WHERE email = ?", (hashed_pw, email))
    cursor.execute("DELETE FROM password_reset_codes WHERE email = ?", (email,))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Password updated successfully'}), 200
