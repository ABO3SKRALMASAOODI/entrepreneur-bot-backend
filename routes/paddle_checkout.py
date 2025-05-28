import os
import requests
from flask import Blueprint, jsonify, request, current_app
from models import get_db
import jwt

print("✅ paddle_checkout.py is being loaded")

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)

@paddle_checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    print("✅ create_checkout_session endpoint was hit")

    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
        print("✅ Token decoded:", payload)
        user_id = payload["sub"]
    except Exception as e:
        print("❌ Token decode error:", str(e))
        return jsonify({"error": "Unauthorized"}), 401

    headers = {
        "Authorization": f"Bearer {os.getenv('PADDLE_API_KEY')}",
        "Content-Type": "application/json"
    }

    data = {
        "customer_id": None,
        "items": [
            {
                "price_id": "pri_01jw8yfkyrrxbr54k86d9dj3ac",
                "quantity": 1
            }
        ],
        "custom_data": {
            "user_id": user_id
        },
        "success_url": "https://entrepreneur-bot-frontend.vercel.app/chat",
        "cancel_url": "https://entrepreneur-bot-frontend.vercel.app/cancel"
    }

    print("[DEBUG] Creating checkout session with:", data)

    res = requests.post("https://api.paddle.com/checkout/sessions", headers=headers, json=data)

    print("[DEBUG] Paddle response:", res.status_code, res.text)

    if res.status_code != 201:
        return jsonify({"error": "Failed to create checkout session", "detail": res.json()}), 500

    return jsonify({"checkout_url": res.json()["data"]["url"]})
