from flask import Flask
from flask_cors import CORS
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.verify_email import verify_bp
from routes.paddle_webhook import paddle_bp
from routes.paddle_checkout import paddle_checkout_bp
from models import init_db
import os
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__)
    CORS(app)
# Triggering redeploy to Render

    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "supersecretkey")
    app.config['DATABASE'] = os.path.join(app.root_path, 'database.db')

    init_db(app)

    # ✅ Register all blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(verify_bp, url_prefix='/verify')
    app.register_blueprint(paddle_bp, url_prefix='/paddle')
    app.register_blueprint(paddle_checkout_bp, url_prefix='/paddle')

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
