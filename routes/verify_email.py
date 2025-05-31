import os
import random
import sqlite3
import requests
from flask import Blueprint, request, jsonify, current_app

verify_bp = Blueprint('verify', __name__)

def get_db():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

@verify_bp.route('/send-code', methods=['POST'])
def send_code():
    email = request.json.get('email')
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    code = str(random.randint(100000, 999999))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO email_codes (email, code) VALUES (?, ?)", (email, code))
    conn.commit()
    conn.close()

    payload = {
        "sender": {
            "name": os.getenv("FROM_NAME"),
            "email": os.getenv("FROM_EMAIL")
        },
        "to": [{"email": email}],
        "subject": "Your Verification Code",
        "htmlContent": f"<p>Your code is: <strong>{code}</strong></p>"
    }

    headers = {
        "accept": "application/json",
        "api-key": os.getenv("BREVO_API_KEY"),
        "content-type": "application/json"
    }

    res = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers)
    if res.status_code != 201:
        return jsonify({'error': 'Failed to send email'}), 500

    return jsonify({'message': 'Verification code sent'}), 200

@verify_bp.route('/verify-code', methods=['POST'])
def verify_code():
    data = request.get_json()
    email = data.get('email')
    code = data.get('code')

    if not email or not code:
        return jsonify({'error': 'Email and code are required'}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM email_codes WHERE email = ?", (email,))
    row = cursor.fetchone()

    if not row:
        return jsonify({'error': 'No code found for this email'}), 400

    if row['code'] != code:
        return jsonify({'error': 'Invalid or expired code'}), 400

    cursor.execute("UPDATE users SET is_verified = 1 WHERE email = ?", (email,))
    cursor.execute("DELETE FROM email_codes WHERE email = ?", (email,))
    conn.commit()
    conn.close()

    return jsonify({'message': 'Email verified successfully'}), 200

def send_code_to_email(email):
    code = str(random.randint(100000, 999999))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO email_codes (email, code) VALUES (?, ?)", (email, code))
    conn.commit()
    conn.close()

    payload = {
        "sender": {
            "name": os.getenv("FROM_NAME"),
            "email": os.getenv("FROM_EMAIL")
        },
        "to": [{"email": email}],
        "subject": "Your Verification Code",
        "htmlContent": f"<p>Your code is: <strong>{code}</strong></p>"
    }

    headers = {
        "accept": "application/json",
        "api-key": os.getenv("BREVO_API_KEY"),
        "content-type": "application/json"
    }

    requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers)
