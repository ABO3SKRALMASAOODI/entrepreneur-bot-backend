import os
import jwt
import requests
from flask import Blueprint, jsonify, request, current_app
from models import get_db
import json

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)

PADDLE_API_URL = "https://api.paddle.com"
PADDLE_API_KEY = "pdl_live_apikey_01jyneav6g1nzqhde0ewmsgnbg_k42qshNW474JzcFgEGZkyN_A4w"

@paddle_checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    print("✅ Paddle create_checkout-session endpoint hit")

    # Decode JWT token
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload["sub"]
    except Exception as e:
        print(f"❌ Token decode error: {e}")
        return jsonify({"error": "Unauthorized"}), 401

    # Fetch user email from DB
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    user_email = user[0]

    headers = {
        "Authorization": f"Bearer {PADDLE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Paddle-Version": "1"
    }

    try:
        # Lookup or create customer
        list_response = requests.get(f"{PADDLE_API_URL}/customers", params={"email": user_email}, headers=headers)
        list_data = list_response.json()
        print("📥 Customer Lookup Response:", json.dumps(list_data, indent=2))

        if list_data.get("data"):
            customer_id = list_data["data"][0]["id"]
            print(f"✅ Existing customer found: {customer_id}")
        else:
            create_payload = {"email": user_email}
            create_response = requests.post(f"{PADDLE_API_URL}/customers", json=create_payload, headers=headers)
            create_data = create_response.json()
            print("📥 Customer Creation Response:", json.dumps(create_data, indent=2))

            if "data" not in create_data or "id" not in create_data["data"]:
                return jsonify({"error": "Failed to create customer"}), 500

            customer_id = create_data["data"]["id"]
            print(f"✅ Customer created: {customer_id}")

        # Create transaction (minimal, let Paddle handle billing details)
        transaction_payload = {
            "items": [
                {
                    "price_id": "pri_01jxj6smtjkfsf22hdr4swyr9j",
                    "quantity": 1
                }
            ],
            "collection_mode": "automatic",
            "customer_id": customer_id,
            "checkout": {
                "success_url": "https://thehustlerbot.com/success",
                "cancel_url": "https://thehustlerbot.com/cancel"
            }
        }

        transaction_response = requests.post(f"{PADDLE_API_URL}/transactions", json=transaction_payload, headers=headers)
        transaction_data = transaction_response.json()
        print("📥 Transaction Response:", json.dumps(transaction_data, indent=2))

        if transaction_response.status_code not in [200, 201] or "data" not in transaction_data:
            return jsonify({"error": "Failed to create transaction"}), 500

        checkout_url = transaction_data["data"].get("checkout", {}).get("url")

        if not checkout_url:
            return jsonify({"error": "Checkout URL not available"}), 500

        return jsonify({"checkout_url": checkout_url})

    except Exception as e:
        print(f"❌ Exception during checkout creation: {e}")
        return jsonify({"error": "Checkout creation failed"}), 500
