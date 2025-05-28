from flask import Blueprint, request, jsonify, current_app
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime

print("auth.py is being imported")

auth_bp = Blueprint('auth', __name__)

def get_db():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

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
    conn.close()

   
    return jsonify({'message': 'User registered successfully'}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    if user and check_password_hash(user['password'], password):
        token = jwt.encode({
            'sub': str(user['id']),
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
        }, current_app.config['SECRET_KEY'], algorithm='HS256')


        return jsonify({'token': token}), 200


    return jsonify({'error': 'Invalid credentials'}), 401
