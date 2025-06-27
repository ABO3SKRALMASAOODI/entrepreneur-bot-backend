import os
import jwt
import requests
import psycopg2
from flask import Blueprint, request, jsonify, current_app
from psycopg2.extras import RealDictCursor
from flask_cors import CORS

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)
CORS(paddle_checkout_bp, supports_credentials=True)

PADDLE_API_URL = "https://api.paddle.com"
PADDLE_API_KEY = os.getenv("PADDLE_API_KEY")
PADDLE_VENDOR_ID = os.getenv("PADDLE_VENDOR_ID")
PRODUCT_PRICE_ID = os.getenv("PADDLE_PRICE_ID")

def get_db():
    return psycopg2.connect(current_app.config['DATABASE_URL'], cursor_factory=RealDictCursor)

@paddle_checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    print(f"Received token: {token}")

    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
        print(f"Decoded payload: {payload}")
        user_id = int(payload["sub"])
    except Exception as e:
        print(f"Token decode failed: {e}")
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    print(f"User lookup result: {user}")

    if not user:
        cursor.close()
        conn.close()
        return jsonify({"error": "User not found"}), 404

    user_email = user['email']
    cursor.close()
    conn.close()

    headers = {
        "Authorization": f"Bearer {PADDLE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Paddle-Version": "1"
    }

    # Lookup or create customer
    res = requests.get(f"{PADDLE_API_URL}/customers", params={"email": user_email}, headers=headers)
    print(f"Customer lookup response: {res.status_code}, {res.text}")
    res_data = res.json()

    if res_data.get("data"):
        customer_id = res_data["data"][0]["id"]
    else:
        create_payload = {"email": user_email}
        res = requests.post(f"{PADDLE_API_URL}/customers", json=create_payload, headers=headers)
        print(f"Customer create response: {res.status_code}, {res.text}")
        res_data = res.json()

        if res.status_code >= 400 or "data" not in res_data:
            return jsonify({"error": "Failed to create customer"}), 400

        customer_id = res_data["data"]["id"]

    # Lookup addresses
    res = requests.get(f"{PADDLE_API_URL}/customers/{customer_id}/addresses", headers=headers)
    print(f"Address lookup response: {res.status_code}, {res.text}")
    res_data = res.json()

    if res_data.get("data"):
        address_id = res_data["data"][0]["id"]
    else:
        address_payload = {
            "description": "Main Address",
            "first_line": "123 Test Street",
            "city": "Dubai",
            "postal_code": "00000",
            "country_code": "AE"
        }
        res = requests.post(f"{PADDLE_API_URL}/customers/{customer_id}/addresses", json=address_payload, headers=headers)
        print(f"Address create response: {res.status_code}, {res.text}")
        res_data = res.json()

        if res.status_code >= 400 or "data" not in res_data:
            return jsonify({"error": "Failed to create address"}), 400

        address_id = res_data["data"]["id"]
    print(f"DEBUG: PRODUCT_PRICE_ID at runtime = {PRODUCT_PRICE_ID}")
    print(f"DEBUG: PADDLE_API_KEY at runtime = {PADDLE_API_KEY}")
    print(f"DEBUG: PADDLE_VENDOR_ID at runtime = {PADDLE_VENDOR_ID}")

    # Create transaction
    transaction_payload = {
        "items": [{"price_id": PRODUCT_PRICE_ID, "quantity": 1}],
        "collection_mode": "automatic",
        "customer_id": customer_id,
        "address_id": address_id,
        "checkout": {
            "success_url": "https://thehustlerbot.com/success",
            "cancel_url": "https://thehustlerbot.com/cancel"
        }
    }

    res = requests.post(f"{PADDLE_API_URL}/transactions", json=transaction_payload, headers=headers)
    print(f"Transaction response: {res.status_code}, {res.text}")
    transaction_data = res.json()

    if res.status_code >= 400 or "data" not in transaction_data or transaction_data["data"]["status"] != "ready":
        return jsonify({"error": "Transaction not ready"}), 500
    transaction_id = transaction_data["data"]["id"]
    checkout_url = transaction_data["data"]["checkout"]["url"]
    print(f"✅ Returning checkout URL: {checkout_url}")
    return jsonify({
    "checkout_url": checkout_url,
    "transaction_id": transaction_data["data"]["id"]
})
