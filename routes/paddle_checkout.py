import os
import requests
from flask import Blueprint, jsonify, request
from models import get_db
import jwt

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)

@paddle_checkout_bp.route('/paddle/create-checkout-session', methods=['POST'])
def create_checkout_session():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=["HS256"])
        user_id = payload["sub"]
    except Exception:
        return jsonify({"error": "Unauthorized"}), 401

    headers = {
        "Authorization": f"Bearer {os.getenv('PADDLE_API_KEY')}",
        "Content-Type": "application/json"
    }

    data = {
        "customer_id": None,
        "items": [
            {
                "price_id": "pri_01jw8722trngfyz12kq158vrz7",  # replace with your actual price ID
                "quantity": 1
            }
        ],
        "custom_data": {
            "user_id": user_id
        },
        "success_url": "https://entrepreneur-bot-frontend.vercel.app/chat",
        "cancel_url": "https://entrepreneur-bot-frontend.vercel.app/cancel"
    }

    # ✅ These lines must be indented inside the function
    print("[DEBUG] Creating checkout session with:", data)

    res = requests.post("https://api.paddle.com/v1/checkout/sessions", headers=headers, json=data)

    print("[DEBUG] Paddle response:", res.status_code, res.text)

    if res.status_code != 201:
        return jsonify({"error": "Failed to create checkout session", "detail": res.json()}), 500

    return jsonify({"checkout_url": res.json()["data"]["url"]})
