import os
import jwt
import requests
from flask import Blueprint, jsonify, request, current_app
from models import get_db
import json

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)

@paddle_checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    print("✅ create_checkout_session endpoint was hit")
    print("🧪 USING TRANSACTIONS ENDPOINT (Paddle Billing)")

    # Decode JWT token
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload["sub"]
    except Exception as e:
        print("❌ Token decode error:", str(e))
        return jsonify({"error": "Unauthorized"}), 401

    # Fetch user email from DB
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    user_email = user[0]

    # Paddle Billing /transactions payload
    payload = {
        "items": [
            {
                "price_id": "pri_01jxj6smtjkfsf22hdr4swyr9j",
                "quantity": 1
            }
        ],
        "collection_mode": "automatic",
        "customer": {
            "email": user_email
        },
        "checkout": {
            "url": "https://thehustlerbot.com/chat"
        }
    }

    headers = {
        "Authorization": f"Bearer {os.environ.get('PADDLE_API_KEY')}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Paddle-Version": "1"
    }

    print("📦 Payload to Paddle:", json.dumps(payload, indent=2))
    print("🔗 POST https://api.paddle.com/transactions")
    print("🔑 API Key Prefix:", os.environ.get("PADDLE_API_KEY")[:15], "...")

    try:
        response = requests.post(
            "https://api.paddle.com/transactions",
            json=payload,
            headers=headers
        )

        data = response.json()
        print("📥 Paddle Response:", json.dumps(data, indent=2))

        if response.status_code != 200 or "data" not in data or "checkout" not in data["data"] or "url" not in data["data"]["checkout"]:
            print("❌ Full error:", response.status_code, response.text)
            return jsonify({"error": "Failed to create Paddle transaction"}), 500

        return jsonify({"checkout_url": data["data"]["checkout"]["url"]})

    except Exception as e:
        print("❌ Exception:", str(e))
        return jsonify({"error": "Checkout creation failed"}), 500
