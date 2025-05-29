from flask import Blueprint, request, jsonify, current_app
import jwt
import sqlite3
import openai
from functools import wraps
import os
from jwt import ExpiredSignatureError, InvalidTokenError

chat_bp = Blueprint('chat', __name__)
print("✅ chat.py with GPT-4 is active")

openai.api_key = os.getenv("OPENAI_API_KEY")

# ----- Database Access -----
def get_db():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

# ----- JWT Token Checker -----
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split(" ")
            if len(parts) == 2 and parts[0] == "Bearer":
                token = parts[1]

        if not token:
            return jsonify({'error': 'Token missing'}), 401

        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = data['sub']  # ✅ Fixed key from 'user_id' to 'sub'
        except ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 403

        return f(user_id, *args, **kwargs)
    return decorated

# ----- Subscription Check -----
def is_user_subscribed(user_id):
    return True  # ✅ Temporarily allow all users for testing

# ----- GPT-4 Chat Endpoint -----
@chat_bp.route('/', methods=['POST'])
@token_required
def chat(user_id):
    if not is_user_subscribed(user_id):
        return jsonify({'error': 'Subscription required'}), 402

    data = request.get_json()
    prompt = data.get('prompt')

    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a business mentor for entrepreneurs."},
                {"role": "user", "content": prompt}
            ]
        )
        reply = response['choices'][0]['message']['content']
        return jsonify({'reply': reply}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
