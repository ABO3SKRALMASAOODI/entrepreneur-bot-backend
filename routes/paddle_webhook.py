from flask import Blueprint, request
import json

paddle_webhook = Blueprint('paddle_webhook', __name__)

@paddle_webhook.route('/webhook/paddle', methods=['POST'])
def handle_webhook():
    data = request.form.to_dict()
    alert_name = data.get('alert_name')

    if alert_name == 'subscription_created':
        passthrough = data.get('passthrough')
        user_id = None
        if passthrough:
            try:
                user_id = json.loads(passthrough).get('user_id')
            except:
                user_id = passthrough

        if user_id:
            from models import upgrade_user_to_premium
            upgrade_user_to_premium(user_id)
            print(f"User {user_id} upgraded to premium.")

    return 'OK', 200
