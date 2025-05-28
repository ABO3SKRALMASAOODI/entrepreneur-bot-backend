import os
import jwt
import urllib.parse
from flask import Blueprint, jsonify, request, current_app
from models import get_db

print("✅ paddle_checkout.py is being loaded")

paddle_checkout_bp = Blueprint('paddle_checkout', __name__)

@paddle_checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    print("✅ create_checkout_session endpoint was hit")

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
        user_id = payload["sub"]
    except Exception as e:
        print("❌ Token decode error:", str(e))
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404

    user_email = user["email"]
    product_id = "pro_01jw8yexc9txg8m9sajthj2ayt"
    
    # 🧠 Properly encode the JSON passthrough
    passthrough_data = urllib.parse.quote(f'{{"user_id": {user_id}}}')

    checkout_url = (
        f"https://checkout.paddle.com/checkout/product/{product_id}"
        f"?email={user_email}"
        f"&passthrough={passthrough_data}"
        f"&success=https://entrepreneur-bot-frontend.vercel.app/chat"
        f"&cancel_url=https://entrepreneur-bot-frontend.vercel.app/cancel"
    )

    print("✅ Final Paddle Checkout URL:", checkout_url)
    return jsonify({"checkout_url": checkout_url})
