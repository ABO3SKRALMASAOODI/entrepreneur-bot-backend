from flask import Blueprint, request
import json
from models import upgrade_user_to_premium  # ✅ Import it here, don't redefine

paddle_webhook = Blueprint('paddle_webhook', __name__)

@paddle_webhook.route('/webhook/paddle', methods=['POST'])
def handle_webhook():
    data = request.form.to_dict()
    alert_name = data.get('alert_name')

    if alert_name == 'subscription_created':
        passthrough = data.get('passthrough')
        if passthrough:
            try:
                parsed_data = json.loads(passthrough)
                user_id = parsed_data.get('user_id')
                if user_id:
                    upgrade_user_to_premium(user_id)
                    print(f"✅ User {user_id} upgraded to premium.")
            except Exception as e:
                print("Failed to parse passthrough:", passthrough)
    
    return 'OK', 200
