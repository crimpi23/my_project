import os
import tempfile
import psycopg2
from flask import Flask, request, render_template, jsonify, redirect, url_for, session, make_response
from werkzeug.utils import secure_filename
from import_data import import_to_db  # Імпортуємо функцію з import_data.py
from flask_wtf.csrf import CSRFProtect
from datetime import datetime, timedelta
import pytz
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
csrf = CSRFProtect(app)

# Налаштування логування
logging.basicConfig(level=logging.DEBUG)

# Заборона кешування статичних файлів
@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response

# Підключення до бази даних
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logging.error("DATABASE_URL is not set")
        raise Exception("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode='require')

# Генерація токена
def generate_token():
    return os.urandom(16).hex()

# Головна сторінка
@app.route("/", methods=["GET"])
def index():
    if 'token' not in session:
        session['token'] = generate_token()
    token = session['token']
    return render_template("index.html", token=token)

# Пошук артикула
@app.route("/search", methods=["GET"])
def search():
    token = session.get('token')
    if not token:
        return redirect(url_for('index'))
    article = request.args.get('article')
    articles = request.args.get('articles')
    error = None
    results = {}

    if not article and not articles:
        return render_template("index.html", token=token, article=article, articles=articles, results=results, error=error)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Отримуємо всі таблиці прайс-листів
        cursor.execute("SELECT table_name FROM price_lists")
        tables = cursor.fetchall()

        if article:
            for table in tables:
                table_name = table[0]
                cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = %s", (article,))
                rows = cursor.fetchall()
                if rows:
                    results[article] = [{"table": table_name, "price": row[1]} for row in rows]

        elif articles:
            articles_list = [a.strip() for a in articles.split('\n') if a.strip()]
            for table in tables:
                table_name = table[0]
                cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = ANY(%s::text[])", (articles_list,))
                rows = cursor.fetchall()
                for row in rows:
                    article = row[0]
                    if article not in results:
                        results[article] = []
                    results[article].append({"table": table_name, "price": row[1]})

        cursor.close()
        conn.close()

        if not results:
            error = "Артикул(и) не знайдено в жодній таблиці"

    except Exception as e:
        error = str(e)
        logging.error(f"Error occurred during search: {e}")

    return render_template("index.html", token=token, article=article, articles=articles, results=results, error=error)

# Рути для інших функцій (наприклад, кошик, завантаження прайс-листів)
# Переконайтеся, що всі функції перевіряють токен у сесії.
# ...

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
