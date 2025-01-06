
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    migrate.init_app(app, db)

    from .routes import main
    from .admin_routes import admin
    from .client_routes import client

    app.register_blueprint(main)
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(client, url_prefix="/client")

    return app
