from flask import Blueprint, request
import json
from models import update_user_subscription_status  # Use the new function
from datetime import datetime

paddle_webhook = Blueprint('paddle_webhook', __name__)

@paddle_webhook.route('/webhook/paddle', methods=['POST'])
def handle_webhook():
    data = request.form.to_dict()
    alert_name = data.get('alert_name')
    passthrough = data.get('passthrough')
    
    try:
        parsed_data = json.loads(passthrough) if passthrough else {}
        user_id = parsed_data.get('user_id')
    except Exception:
        user_id = None

    if not user_id:
        print("User ID missing in webhook passthrough")
        return 'OK', 200

    # Handle subscription created or payment succeeded - activate subscription
    if alert_name in ('subscription_created', 'subscription_payment_succeeded'):
        # Paddle sends next payment due date in 'next_bill_date' field (YYYY-MM-DD)
        next_bill_date_str = data.get('next_bill_date')
        expiry_date = None
        if next_bill_date_str:
            try:
                expiry_date = datetime.strptime(next_bill_date_str, '%Y-%m-%d')
            except Exception:
                expiry_date = None

        update_user_subscription_status(user_id, True, expiry_date)
        print(f"✅ User {user_id} subscription activated until {expiry_date}")

    # Handle subscription cancelled or payment failed - deactivate subscription
    elif alert_name in ('subscription_cancelled', 'subscription_payment_failed', 'subscription_payment_refunded'):
        update_user_subscription_status(user_id, False, None)
        print(f"⚠️ User {user_id} subscription deactivated due to {alert_name}")

    # Other webhook events can be handled here...

    return 'OK', 200
