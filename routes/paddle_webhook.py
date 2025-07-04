from flask import Blueprint, request
import json
from models import update_user_subscription_status
from datetime import datetime

paddle_webhook = Blueprint('paddle_webhook', __name__)
@paddle_webhook.route('/webhook/paddle', methods=['POST'])
def handle_webhook():
    data = request.form.to_dict()
    
    print(f"🔔 Full webhook payload: {data}")  # <<< ADD THIS LINE

    alert_name = data.get('alert_name')
    custom_data_str = data.get('custom_data')
    passthrough_str = data.get('passthrough')

    user_id = None

    if custom_data_str:
        try:
            parsed = json.loads(custom_data_str)
            user_id = parsed.get('user_id')
            print(f"✅ Found user_id in custom_data: {user_id}")
        except Exception as e:
            print(f"⚠️ Failed to parse custom_data JSON: {e}")

    if not user_id and passthrough_str:
        try:
            parsed = json.loads(passthrough_str)
            user_id = parsed.get('user_id')
            print(f"✅ Found user_id in passthrough: {user_id}")
        except Exception as e:
            print(f"⚠️ Failed to parse passthrough JSON: {e}")

    if not user_id:
        print(f"❌ User ID missing for alert {alert_name}, ignoring.")
        return 'OK', 200

    # Handle subscription activation
    if alert_name in ('subscription_created', 'subscription_payment_succeeded'):
        next_bill_date_str = data.get('next_bill_date')
        expiry_date = None
        if next_bill_date_str:
            try:
                expiry_date = datetime.strptime(next_bill_date_str, '%Y-%m-%d')
            except Exception:
                expiry_date = None

        update_user_subscription_status(user_id, True, expiry_date)
        print(f"✅ User {user_id} subscription activated until {expiry_date}")

    elif alert_name in ('subscription_cancelled', 'subscription_payment_failed', 'subscription_payment_refunded'):
        update_user_subscription_status(user_id, False, None)
        print(f"⚠️ User {user_id} subscription deactivated due to {alert_name}")

    return 'OK', 200
