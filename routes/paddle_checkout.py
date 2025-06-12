import os
import jwt
import requests
from flask import Blueprint, jsonify, request, current_app
from models import get_db

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)

@paddle_checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    print("✅ create_checkout_session endpoint was hit")

    # 1. Decode token to get user_id
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload["sub"]
    except Exception as e:
        print("❌ Token decode error:", str(e))
        return jsonify({"error": "Unauthorized"}), 401

    # 2. Fetch user email
    conn = get_db()
    cursor = conn.cursor()
   cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    user_email = user["email"]

    # 3. Prepare payload for Paddle Billing checkout
    payload = {
        "customer": {
            "email": user_email
        },
        "items": [
            {
                "price_id": "pri_01jw8yfkyrxxbr54k86d9dj3ac",  # Your actual price ID
                "quantity": 1
            }
        ],
        "return_url": "https://entrepreneur-bot-frontend.vercel.app/chat"
    }

    headers = {
        "Authorization": f"Bearer {os.environ.get('PADDLE_API_KEY')}",
        "Content-Type": "application/json"
    }

    # 4. Make request to Paddle Billing API
    try:
        response = requests.post("https://api.paddle.com/v1/checkouts", json=payload, headers=headers)
        data = response.json()
        print("✅ Paddle response:", data)

        if not data.get("data") or "url" not in data["data"]:
            return jsonify({"error": "Failed to create session"}), 500

        return jsonify({"checkout_url": data["data"]["url"]})
    except Exception as e:
        print("❌ Exception:", str(e))
        return jsonify({"error": "Checkout creation failed"}), 500
