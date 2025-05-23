from flask import Blueprint, request, jsonify, current_app
import stripe
import os
import jwt
from functools import wraps
import sqlite3

checkout_bp = Blueprint('checkout', __name__)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
YOUR_DOMAIN = "https://entrepreneur-bot-frontend.vercel.app"

def get_db():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = data['user_id']
        except:
            return jsonify({'error': 'Invalid token'}), 403
        return f(user_id, *args, **kwargs)
    return decorated

@checkout_bp.route('/create-checkout-session', methods=['POST'])
@token_required
def create_checkout_session(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='subscription',
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Entrepreneur AI Coach',
                    },
                    'unit_amount': 999,
                    'recurring': {
                        'interval': 'month',
                    },
                },
                'quantity': 1,
            }],
            customer_email=user['email'],
            success_url=f"{YOUR_DOMAIN}/chat",
            cancel_url=f"{YOUR_DOMAIN}/subscribe"
        )
        return jsonify({'checkout_url': checkout_session.url})  # ✅ correct indentation

    except Exception as e:
        return jsonify({'error': str(e)}), 500
