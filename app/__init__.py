from flask import Flask
from flask_wtf.csrf import CSRFProtect
import os
import psycopg2
from psycopg2 import pool
from urllib.parse import urlparse

csrf = CSRFProtect()

def create_app():
    app = Flask(__name__, static_folder='static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key')

    db_url = os.getenv('DATABASE_URL')
    result = urlparse(db_url)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port

    app.config['POOL'] = psycopg2.pool.SimpleConnectionPool(
        1, 20,
        user=username,
        password=password,
        host=hostname,
        port=port,
        database=database
    )

    csrf.init_app(app)

    with app.app_context():
        from . import routes
        app.register_blueprint(routes.bp)

    @app.route('/static/<path:filename>')
    def static_files(filename):
        return app.send_static_file(filename)

    return app
