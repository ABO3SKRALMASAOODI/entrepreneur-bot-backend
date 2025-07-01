from flask import Blueprint, request, jsonify
import requests
import os
import json
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

    # Create checkout link via Paddle API
    url = "https://api.paddle.com/checkout/sessions"

    headers = {
        "Authorization": f"Bearer {os.environ['PADDLE_API_KEY']}",
        "Content-Type": "application/json"
    }

    body = {
        "customer": { "email": payload.get('email') },
        "items": [
            { "price_id": "pri_01jynfg4knxtn69ncekyxg2cjz", "quantity": 1 }
        ],
        "custom_data": json.dumps({ "user_id": user_id }),
        "redirect_url": "https://thehustlerbot.com/paddle-checkout"
    }

    response = requests.post(url, headers=headers, json=body)
    if response.status_code != 201:
        return jsonify({"error": "Failed to create checkout session", "details": response.text}), 500

    checkout_data = response.json()
    checkout_url = checkout_data['data']['url']

    return jsonify({ "checkout_url": checkout_url })
