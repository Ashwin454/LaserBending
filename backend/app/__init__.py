from flask import Flask
from config import Config
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
import os

db = SQLAlchemy()
mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)

    # Set up uploads folder
    UPLOAD_FOLDER = 'Uploads'
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # CORS for frontend origins
    origins = ["http://localhost:3000", "http://10.50.45.244:8081"]
    CORS(app, resources={
        r"/auth/*": {"origins": origins},
        r"/save-snapshot": {"origins": origins}
    })

    # Register blueprints
    from app.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    return app