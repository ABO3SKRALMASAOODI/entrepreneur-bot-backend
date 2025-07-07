from flask import Blueprint, request, jsonify, current_app
import jwt
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import random

auth_bp = Blueprint('auth', __name__)

# Your existing get_db function...

def get_db():
    return psycopg2.connect(current_app.config['DATABASE_URL'], cursor_factory=RealDictCursor)

# --- JWT token decorator to extract user_id ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header[len('Bearer '):]
        if not token:
            return jsonify({'error': 'Token is missing!'}), 401
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = data['sub']
        except Exception as e:
            return jsonify({'error': 'Token is invalid!'}), 401
        return f(user_id=user_id, *args, **kwargs)
    return decorated

# --- New route to check subscription ---
@auth_bp.route('/status/subscription', methods=['GET'])
@token_required
def check_subscription(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_subscribed FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    is_subscribed = bool(row['is_subscribed']) if row else False
    return jsonify({'is_subscribed': is_subscribed})

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

    # Auto-delete unverified users older than 1 minute
    cursor.execute("""
        DELETE FROM users
        WHERE email = %s AND is_verified = 0 AND created_at < NOW() - INTERVAL '5 minute'
    """, (email,))
    conn.commit()

    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    hashed_pw = generate_password_hash(password)

    if user:
        if user['is_verified'] == 0:
            # Update password & resend code
            cursor.execute("UPDATE users SET password = %s WHERE email = %s", (hashed_pw, email))
            conn.commit()

            code = str(random.randint(100000, 999999))
            cursor.execute("""
                INSERT INTO email_codes (email, code)
                VALUES (%s, %s)
                ON CONFLICT (email) DO UPDATE SET code = EXCLUDED.code
            """, (email, code))
            conn.commit()

            send_code_to_email(email, code)

            cursor.close()
            conn.close()
            return jsonify({'message': 'Verification code re-sent. Please verify your email.'}), 200
        else:
            cursor.close()
            conn.close()
            return jsonify({'error': 'User already exists'}), 409

    # New user
    cursor.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed_pw))
    conn.commit()

    code = str(random.randint(100000, 999999))
    cursor.execute("""
        INSERT INTO email_codes (email, code)
        VALUES (%s, %s)
        ON CONFLICT (email) DO UPDATE SET code = EXCLUDED.code
    """, (email, code))
    conn.commit()

    send_code_to_email(email, code)
    cursor.close()
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
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user or user['is_verified'] == 0:
        return jsonify({'error': 'User not found. Please register.'}), 404

    if not check_password_hash(user['password'], password):
        return jsonify({'error': 'Incorrect password'}), 401

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
    # Only allow verified users to reset password
    cursor.execute("SELECT * FROM users WHERE email = %s AND is_verified = 1", (email,))
    if not cursor.fetchone():
        return jsonify({'error': 'User not found or not verified'}), 404

    code = str(random.randint(100000, 999999))
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat()

    cursor.execute("""
        INSERT INTO password_reset_codes (email, code, expires_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (email) DO UPDATE SET code = EXCLUDED.code, expires_at = EXCLUDED.expires_at
    """, (email, code, expires_at))
    conn.commit()
    cursor.close()
    conn.close()

    send_code_to_email(email, code)
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
    cursor.execute("SELECT code, expires_at FROM password_reset_codes WHERE email = %s", (email,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({'error': 'No code found'}), 404

    if str(row['code']).strip() != str(code).strip():
        return jsonify({'error': 'Incorrect code'}), 400

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
    cursor.execute("UPDATE users SET password = %s WHERE email = %s", (hashed_pw, email))
    cursor.execute("DELETE FROM password_reset_codes WHERE email = %s", (email,))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'message': 'Password updated successfully'}), 200
