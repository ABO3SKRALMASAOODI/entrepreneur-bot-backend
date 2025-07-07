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

    # Process only relevant events
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

    # Extract user_id safely
    custom_data = data.get('custom_data') or {}
    user_id = custom_data.get('user_id')

    if not user_id:
        print(f"❌ User ID missing for event {event_type}, ignoring.")
        return 'OK', 200

    # Handle transaction-based activation (don't update subscription_id)
    if event_type in ('transaction.completed', 'transaction.paid'):
        expiry_date_str = data.get('next_billed_at')
        expiry_date = None

        if expiry_date_str:
            try:
                expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%dT%H:%M:%SZ')
            except Exception as e:
                print(f"⚠️ Failed to parse expiry_date: {e}")

        update_user_subscription_status(user_id, True, expiry_date)
        print(f"✅ User {user_id} subscription activated until {expiry_date} (transaction event)")

    # Handle subscription creation or update (update subscription_id)
    elif event_type in ('subscription.created', 'subscription.updated'):
        expiry_date_str = data.get('next_billed_at')
        subscription_id = data.get('id')  # This is the correct subscription ID
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
