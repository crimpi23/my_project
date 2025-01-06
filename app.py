import os
import tempfile
import psycopg2
from flask import Flask, request, render_template, jsonify, redirect, url_for, session
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

# Перевірка токена
def validate_token(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return user is not None
    except Exception as e:
        logging.error(f"Error validating token: {e}")
        return False

# Головна сторінка
@app.route("/", methods=["GET"])
def index():
    if 'token' not in session:
        session['token'] = generate_token()
        logging.info(f"Generated new token: {session['token']}")
    token = session['token']
    if not validate_token(token):
        return "Invalid token", 403
    return render_template("index.html", token=token)

# Пошук артикула
@app.route("/search", methods=["GET"])
def search():
    token = session.get('token')
    if not token or not validate_token(token):
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

# Завантаження прайс-листів
@app.route("/upload", methods=["GET", "POST"])
def upload():
    token = session.get('token')
    if not token or not validate_token(token):
        return redirect(url_for('index'))

    if request.method == "GET":
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'vag%'")
            tables = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception as e:
            logging.error(f"Error fetching tables: {e}")
            return jsonify({"error": str(e)}), 500
        return render_template("upload.html", tables=[t[0] for t in tables], token=token)

    if request.method == "POST":
        file = request.files.get('file')
        table = request.form.get('table')

        if file and table:
            filename = secure_filename(file.filename)

            # Використання тимчасової директорії для зберігання файлу
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file_path = temp_file.name
                file.save(file_path)

            try:
                import_to_db(table, file_path)
                os.remove(file_path)  # Видалення тимчасового файлу після використання
                return jsonify({"message": f"Файл {filename} успішно завантажено в таблицю {table}"}), 200
            except Exception as e:
                logging.error(f"Error during import: {e}")
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Необхідно вибрати файл і таблицю"}), 400

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
