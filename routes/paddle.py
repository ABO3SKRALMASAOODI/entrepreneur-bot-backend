from flask import Blueprint, request, jsonify
import requests
import os
import jwt

paddle_bp = Blueprint('paddle', __name__)
print("PADDLE_API_KEY from environment:", os.environ.get('PADDLE_API_KEY'))
print("PADDLE_MODE from environment:", os.environ.get('PADDLE_MODE'))

@paddle_bp.route('/paddle/create-checkout-session', methods=['POST'])
def create_checkout_session():
    # Authenticate the user via token
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing token"}), 401

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload.get('user_id')
        user_email = payload.get('email')
    except Exception as e:
        return jsonify({"error": "Invalid token"}), 401

    # Determine API URL based on environment
    is_sandbox = os.environ.get('PADDLE_MODE') == 'sandbox'
    api_base = "https://sandbox-api.paddle.com" if is_sandbox else "https://api.paddle.com"

    url = f"{api_base}/transactions"
    headers = {
        "Authorization": f"Bearer {os.environ['PADDLE_API_KEY']}",
        "Content-Type": "application/json"
    }

    body = {
        "items": [
            {
                "price_id": os.environ["PADDLE_PRICE_ID"],
                "quantity": 1
            }
        ],
        "customer": { "email": user_email },
        "custom_data": { "user_id": user_id },
        "collection_mode": "automatic",
        "checkout": {
            "success_url": "https://thehustlerbot.com/chat"
        }
    }

    response = requests.post(url, headers=headers, json=body)
    print("Raw Paddle API Response:", response.text)

    if response.status_code != 201:
        print("Paddle Error:", response.text)
        return jsonify({"error": "Failed to create checkout session", "details": response.text}), 500

    data = response.json()
    checkout_url = data["data"]["checkout"]["url"]

    print("Generated Checkout URL:", checkout_url)

    return jsonify({"checkout_url": checkout_url})
