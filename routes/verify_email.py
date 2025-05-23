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
