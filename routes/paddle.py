from flask import Blueprint, request, jsonify
import requests
import os
import jwt

paddle_bp = Blueprint('paddle', __name__)
print("PADDLE_API_KEY from environment:", os.environ.get('PADDLE_API_KEY'))
print("PADDLE_MODE from environment:", os.environ.get('PADDLE_MODE'))

@paddle_bp.route('/paddle/create-checkout-session', methods=['POST'])
def create_checkout_session():
    # Authenticate the user via token
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing token"}), 401

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload.get('sub')
        user_email = payload.get('email')
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

    # Determine API URL based on environment
    is_sandbox = os.environ.get('PADDLE_MODE') == 'sandbox'
    api_base = "https://sandbox-api.paddle.com" if is_sandbox else "https://api.paddle.com"

    url = f"{api_base}/transactions"
    headers = {
        "Authorization": f"Bearer {os.environ['PADDLE_API_KEY']}",
        "Content-Type": "application/json"
    }

    body = {
        "items": [
            {
                "price_id": os.environ["PADDLE_PRICE_ID"],
                "quantity": 1
            }
        ],
        "customer": { "email": user_email },
        "custom_data": { "user_id": user_id },
        "collection_mode": "automatic",
        "checkout": {
            "success_url": "https://thehustlerbot.com/chat"
        }
    }

    response = requests.post(url, headers=headers, json=body)
    print("Raw Paddle API Response:", response.text)

    if response.status_code != 201:
        print("Paddle Error:", response.text)
        return jsonify({"error": "Failed to create checkout session", "details": response.text}), 500

    data = response.json()
    checkout_url = data["data"]["checkout"]["url"]

    print("Generated Checkout URL:", checkout_url)

    return jsonify({"checkout_url": checkout_url})
@paddle_bp.route('/paddle/cancel-subscription', methods=['POST'])
def cancel_subscription():
    # Authenticate user
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing token"}), 401

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload.get('sub')
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

    # Fetch subscription ID from database
    from models import get_user_subscription_id
    subscription_id = get_user_subscription_id(user_id)
    if not subscription_id:
        return jsonify({"error": "No active subscription found"}), 400

    # Determine API URL
    is_sandbox = os.environ.get('PADDLE_MODE') == 'sandbox'
    api_base = "https://sandbox-api.paddle.com" if is_sandbox else "https://api.paddle.com"

    url = f"{api_base}/subscriptions/{subscription_id}/cancel"
    headers = {
        "Authorization": f"Bearer {os.environ['PADDLE_API_KEY']}",
        "Content-Type": "application/json"
    }

    # Correct cancellation logic
    response = requests.post(url, headers=headers, json={"effective_from": "next_billing_period"})
    if response.status_code not in (200, 204):
        print("Paddle Cancel Error:", response.text)
        return jsonify({"error": "Failed to cancel subscription", "details": response.text}), 500

    print(f"✅ Subscription {subscription_id} scheduled for cancellation at period end")
    return jsonify({"message": "Subscription will not renew. You'll keep access until the end of the billing period."}) paddle_webhook.py: from flask import Blueprint, request
from models import update_user_subscription_status
from datetime import datetime

paddle_webhook = Blueprint('paddle_webhook', __name__)

@paddle_webhook.route('/webhook/paddle', methods=['POST'])
def handle_webhook():
    payload = request.get_json()
    print(f"🔔 Full webhook payload: {payload}")

    event_type = payload.get('event_type')
    data = payload.get('data', {})

    # Only process relevant events
    if event_type not in (
        'transaction.completed',
        'transaction.paid',
        'subscription.created',
        'subscription.updated',
        'subscription.canceled',
        'subscription.payment_failed',
        'subscription.payment_refunded'
    ):
        print(f"ℹ️ Ignoring irrelevant event: {event_type}")
        return 'OK', 200

    # Extract user_id
    custom_data = data.get('custom_data') or {}
    user_id = custom_data.get('user_id')

    if not user_id:
        print(f"❌ User ID missing for event {event_type}, ignoring.")
        return 'OK', 200

    # Extract subscription_id if present
    subscription_id = data.get('subscription_id')

    # Handle transaction-based activation
    if event_type in ('transaction.completed', 'transaction.paid'):
        expiry_date_str = data.get('next_billed_at')
        expiry_date = None

        if expiry_date_str:
            try:
                expiry_date = datetime.fromisoformat(expiry_date_str.replace("Z", "+00:00"))
            except Exception as e:
                print(f"⚠️ Failed to parse expiry_date: {e}")

        update_user_subscription_status(user_id, True, expiry_date, subscription_id)
        print(f"✅ User {user_id} subscription activated until {expiry_date} (transaction event)")

    # Handle subscription creation or update
    elif event_type in ('subscription.created', 'subscription.updated'):
        expiry_date_str = data.get('next_billed_at')
        subscription_id = data.get('id')  # Subscription ID always in 'id' for these events
        expiry_date = None

        if expiry_date_str:
            try:
                expiry_date = datetime.fromisoformat(expiry_date_str.replace("Z", "+00:00"))
            except Exception as e:
                print(f"⚠️ Failed to parse expiry_date: {e}")

        update_user_subscription_status(user_id, True, expiry_date, subscription_id)
        print(f"✅ User {user_id} subscription activated until {expiry_date}, Subscription ID: {subscription_id}")

    # Handle subscription deactivation
    elif event_type in ('subscription.canceled', 'subscription.payment_failed', 'subscription.payment_refunded'):
        update_user_subscription_status(user_id, False, None)
        print(f"⚠️ User {user_id} subscription deactivated due to {event_type}")

    return 'OK', 200 