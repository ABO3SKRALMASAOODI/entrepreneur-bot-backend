from flask import Blueprint, request
import sqlite3
import os
from models import get_db

paddle_bp = Blueprint('paddle', __name__)

@paddle_bp.route('/paddle/webhook', methods=['POST'])
def paddle_webhook():
    data = request.form.to_dict()
    event_type = data.get('alert_name')

    if event_type == 'payment_succeeded':
        try:
            passthrough = data.get('passthrough')
            if not passthrough:
                return "Missing passthrough", 400

            import json
            user_data = json.loads(passthrough)
            user_id = user_data.get("user_id")

            if not user_id:
                return "Missing user_id in passthrough", 400

            db = get_db()
            cursor = db.cursor()
            cursor.execute("UPDATE users SET is_subscribed = 1 WHERE id = ?", (user_id,))
            db.commit()
            return "OK", 200

        except Exception as e:
            print("[Webhook Error]", str(e))
            return "Error", 500

    return "Unhandled event", 200
