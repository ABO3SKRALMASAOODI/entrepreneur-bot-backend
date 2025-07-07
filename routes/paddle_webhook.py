from flask import Blueprint, request
from models import update_user_subscription_status
from datetime import datetime

paddle_webhook = Blueprint('paddle_webhook', __name__)

@paddle_webhook.route('/webhook/paddle', methods=['POST'])
def handle_webhook():
    payload = request.get_json()
    print(f"🔔 Full webhook payload: {payload}")

    event_type = payload.get('event_type')
    data = payload.get('data', {})

    custom_data = data.get('custom_data', {})
    user_id = custom_data.get('user_id')

    if not user_id:
        print(f"❌ User ID missing for event {event_type}, ignoring.")
        return 'OK', 200

    # Handle subscription activation
    if event_type in ('subscription.created', 'transaction.completed'):
        expiry_date_str = data.get('next_billed_at')  # Adjust field if needed
        expiry_date = None

        if expiry_date_str:
            try:
                expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%dT%H:%M:%SZ')
            except Exception as e:
                print(f"⚠️ Failed to parse expiry_date: {e}")

        update_user_subscription_status(user_id, True, expiry_date)
        print(f"✅ User {user_id} subscription activated until {expiry_date}")

    elif event_type in ('subscription.canceled', 'subscription.payment_failed', 'subscription.payment_refunded'):
        update_user_subscription_status(user_id, False, None)
        print(f"⚠️ User {user_id} subscription deactivated due to {event_type}")

    return 'OK', 200
