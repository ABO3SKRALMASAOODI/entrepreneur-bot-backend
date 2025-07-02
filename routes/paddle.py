from flask import Blueprint, request, jsonify
import requests
import os
import jwt

paddle_bp = Blueprint('paddle', __name__)

@paddle_bp.route('/paddle/create-checkout-session', methods=['POST'])
def create_checkout_session():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing token"}), 401

    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, os.environ['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload.get('user_id')
    except:
        return jsonify({"error": "Invalid token"}), 401

    url = "https://api.paddle.com/transactions"

    headers = {
        "Authorization": f"Bearer {os.environ['PADDLE_API_KEY']}",
        "Content-Type": "application/json"
    }

    body = {
        "items": [
            { "price_id": os.environ['PADDLE_PRICE_ID'], "quantity": 1 }
        ],
        "collection_mode": "automatic",
        "enable_checkout": True,
        "checkout": {
            "url": "https://thehustlerbot.com/paddle-checkout"
        },
        "custom_data": f"user_id={user_id}"
    }

    response = requests.post(url, headers=headers, json=body)

    if response.status_code != 201:
        print("Paddle Error Response:", response.text)
        return jsonify({"error": "Failed to create checkout session", "details": response.text}), 500

    checkout_data = response.json()
    checkout_url = checkout_data['data']['checkout']['url']

    return jsonify({ "checkout_url": checkout_url })
