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
            user_id = data['sub']
        except ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 403

        return f(user_id, *args, **kwargs)
    return decorated

# ----- Subscription Check -----
def is_user_subscribed(user_id):
    return True  # ✅ Temporarily allow all users for testing

# ----- Basic Chat (No Session) -----
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

# ----- Start New Chat Session -----
@chat_bp.route('/start-session', methods=['POST'])
@token_required
def start_session(user_id):
    data = request.get_json()
    title = data.get("title", "Untitled Session")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_sessions (user_id, title) VALUES (?, ?)",
        (user_id, title)
    )
    conn.commit()
    session_id = cursor.lastrowid

    return jsonify({"session_id": session_id}), 201

# ----- Send Message in a Session -----
@chat_bp.route('/send-message', methods=['POST'])
@token_required
def send_message(user_id):
    data = request.get_json()
    session_id = data.get("session_id")
    prompt = data.get("prompt")

    if not session_id or not prompt:
        return jsonify({'error': 'Missing session_id or prompt'}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Insert user message
    cursor.execute('''
        INSERT INTO chat_messages (session_id, role, content)
        VALUES (?, ?, ?)
    ''', (session_id, "user", prompt))

    # Fetch previous messages in session
    cursor.execute("SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    all_messages = cursor.fetchall()

    # Get session info
    cursor.execute("SELECT title FROM chat_sessions WHERE id = ?", (session_id,))
    session = cursor.fetchone()
    title = session["title"] if session else "Untitled Session"

    # 🔍 If it's the 3rd message & still untitled, generate title
    if len(all_messages) == 3 and title == "Untitled Session":
        summary_prompt = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in all_messages[:3]])
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": f"Summarize the following chat as a short session title:\n\n{summary_prompt}\n\nTitle:"}],
                max_tokens=20,
                temperature=0.5,
            )
            new_title = response.choices[0].message["content"].strip()
            if new_title:
                cursor.execute("UPDATE chat_sessions SET title = ? WHERE id = ?", (new_title, session_id))
        except Exception as e:
            print("Error generating title:", str(e))  # Silent fail

    # GPT response
    try:
        reply = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a business mentor for entrepreneurs."},
                *[
                    {"role": m["role"], "content": m["content"]}
                    for m in all_messages
                ],
                {"role": "user", "content": prompt}
            ]
        )["choices"][0]["message"]["content"]
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Insert assistant reply
    cursor.execute('''
        INSERT INTO chat_messages (session_id, role, content)
        VALUES (?, ?, ?)
    ''', (session_id, "assistant", reply))

    conn.commit()
    return jsonify({'reply': reply}), 200

# ----- List All Sessions -----
@chat_bp.route('/sessions', methods=['GET'])
@token_required
def list_sessions(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, created_at FROM chat_sessions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    )
    sessions = [dict(row) for row in cursor.fetchall()]
    return jsonify({"sessions": sessions})

# ----- Get Messages in a Session -----
@chat_bp.route('/messages/<int:session_id>', methods=['GET'])
@token_required
def get_session_messages(user_id, session_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    session = cursor.fetchone()
    if not session:
        return jsonify({"error": "Session not found"}), 404

    cursor.execute(
        "SELECT role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,)
    )
    messages = [dict(row) for row in cursor.fetchall()]
    return jsonify({"messages": messages})
