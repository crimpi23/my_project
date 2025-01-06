import os
import tempfile
import psycopg2
from flask import Flask, request, render_template, jsonify, redirect, url_for, session
from werkzeug.utils import secure_filename
from import_data import import_to_db
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

# Головна сторінка з токеном
@app.route("/<token>/", methods=["GET"])
def index_with_token(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        return render_template("index.html", token=token)
    except Exception as e:
        logging.error(f"Error occurred on the main page: {e}")
        return str(e), 500

# Пошук артикула
@app.route("/<token>/search", methods=["GET"])
def search(token):
    article = request.args.get('article')
    articles = request.args.get('articles')
    error = None
    results = {}

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        if article or articles:
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

# Перегляд кошика
@app.route("/<token>/cart", methods=["GET"])
def view_cart(token):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        user_id = user[0]

        # Отримання вмісту кошика
        cursor.execute("""
            SELECT p.article, p.table_name, p.price, c.quantity, c.added_at, p.id
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        total_price = sum(item[2] * item[3] for item in cart_items)

        utc = pytz.UTC
        now = datetime.now(utc)
        for item in cart_items:
            added_at = item[4].replace(tzinfo=utc)
            if now - added_at > timedelta(hours=24):
                cursor.execute("DELETE FROM cart WHERE user_id = %s AND product_id = %s", (user_id, item[5]))

        conn.commit()
        cursor.close()
        conn.close()

        return render_template("cart.html", token=token, cart_items=cart_items, total_price=total_price)
    except Exception as e:
        logging.error(f"Error occurred while viewing cart: {e}")
        return str(e), 500
@app.route("/<token>/cart", methods=["GET"])
def view_cart(token):
    # Ваш код для відображення кошика
    try:
        # Перевірка валідності токена (при необхідності)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403
        
        user_id = user[0]
        
        # Отримання вмісту кошика
        cursor.execute("""
            SELECT p.article, p.table_name, p.price, c.quantity, c.added_at
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()
        
        total_price = sum(item[2] * item[3] for item in cart_items)
        cursor.close()
        conn.close()
        return render_template("cart.html", token=token, cart_items=cart_items, total_price=total_price)
    except Exception as e:
        logging.error(f"Error while viewing cart: {e}")
        return "Internal Server Error", 500
# Завантаження прайс-листів
@app.route("/<token>/upload", methods=["GET", "POST"])
def upload(token):
    if request.method == "GET":
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'vag%'")
            tables = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception as e:
            logging.error(f"Error occurred while fetching tables: {e}")
            return jsonify({"error": str(e)}), 500
        return render_template("upload.html", tables=[t[0] for t in tables], token=token)

    if request.method == "POST":
        file = request.files.get('file')
        table = request.form.get('table')

        if file and table:
            filename = secure_filename(file.filename)

            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file_path = temp_file.name
                file.save(file_path)

            try:
                import_to_db(table, file_path)
                os.remove(file_path)
                return jsonify({"message": f"Файл {filename} успішно завантажено в таблицю {table}"}), 200
            except Exception as e:
                logging.error(f"Error occurred during import: {e}")
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Необхідно вибрати файл і таблицю"}), 400

# Запуск додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
