from flask import Flask
from flask_cors import CORS
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.verify_email import verify_bp


from models import init_db
import os
from dotenv import load_dotenv
from routes.paypal import paypal_bp
from routes.paddle_webhook import paddle_bp



load_dotenv()

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "supersecretkey")
    app.config['DATABASE_URL'] = os.getenv("DATABASE_URL")


    init_db(app)

    print("✅ paddle_checkout_bp is being registered")

    # ✅ Register Blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(verify_bp, url_prefix='/verify')
    app.register_blueprint(paddle_bp)
    app.register_blueprint(paypal_bp, url_prefix='/paypal')

 

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
