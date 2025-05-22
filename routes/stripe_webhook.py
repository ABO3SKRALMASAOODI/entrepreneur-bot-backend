from flask import Blueprint, request, jsonify, current_app
import stripe
import sqlite3
import os

stripe_bp = Blueprint('stripe', __name__)
print("✅ stripe_webhook.py is being imported")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

def get_db():
    conn = sqlite3.connect(current_app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

@stripe_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_email')

        if customer_email:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_subscribed = 1 WHERE email = ?", (customer_email,))
            conn.commit()
            conn.close()
            print(f"✅ Subscription updated for {customer_email}")

    return jsonify({'status': 'success'}), 200
