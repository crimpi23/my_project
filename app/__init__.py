from flask import Flask
from flask_wtf.csrf import CSRFProtect
import os

csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key')

    csrf.init_app(app)

    with app.app_context():
        from . import routes
        app.register_blueprint(routes.bp)

    return app
