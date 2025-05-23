from flask import Flask
from flask_cors import CORS
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.stripe_webhook import stripe_bp
from routes.stripe_checkout import checkout_bp
from routes.verify_email import verify_bp   # <-- new
from models import init_db
import os
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "supersecretkey")
    app.config['DATABASE'] = os.path.join(app.root_path, 'database.db')

    init_db(app)

    # ✅ Register all blueprints here
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(stripe_bp, url_prefix='/stripe')
    app.register_blueprint(checkout_bp, url_prefix='/stripe')
    app.register_blueprint(verify_bp, url_prefix='/verify')  # <-- new

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
