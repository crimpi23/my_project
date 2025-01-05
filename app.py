import os
import tempfile
import psycopg2
import uuid
from flask import Flask, request, render_template, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
from import_data import import_to_db  # Імпортуємо функцію з import_data.py
import logging
from datetime import datetime, timedelta
import pytz

# Налаштування логування
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Підключення до бази даних
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logging.error("DATABASE_URL is not set")
        raise Exception("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode='require')

# Головна сторінка - з пошуком артикула
@app.route("/<token>/", methods=["GET"])
def index(token):
    article = request.args.get('article')
    articles = request.args.get('articles')
    error = None
    results = {}

    if not article and not articles:
        return render_template("index.html", token=token, article=article, articles=articles, results=results, error=error)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        user_id = user[0]

        if article or articles:
            if article:
                # Отримуємо всі таблиці прайс-листів
                cursor.execute("SELECT table_name FROM price_lists")
                tables = cursor.fetchall()

                # Шукаємо артикул у всіх таблицях
                for table in tables:
                    table_name = table[0]
                    cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = %s", (article,))
                    rows = cursor.fetchall()

                    if rows:
                        if article not in results:
                            results[article] = []
                        for row in rows:
                            results[article].append({"table": table_name, "price": row[1]})
            
            elif articles:
                # Розділяємо артикули по нових рядках
                articles_list = [a.strip() for a in articles.split('\n') if a.strip()]
                
                # Отримуємо всі таблиці прайс-листів
                cursor.execute("SELECT table_name FROM price_lists")
                tables = cursor.fetchall()

                # Шукаємо артикули у всіх таблицях
                for table in tables:
                    table_name = table[0]
                    # Використовуємо ANY для пошуку кожного артикула
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

# Додавання продукту в корзину
@app.route("/<token>/add_to_cart", methods=["POST"])
def add_to_cart(token):
    article = request.form.get('article')
    table = request.form.get('table')
    price = request.form.get('price')
    quantity = int(request.form.get('quantity', 1))

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        user_id = user[0]

        # Перевірка, чи вже існує продукт в таблиці products
        cursor.execute("SELECT id FROM products WHERE article = %s AND table_name = %s", (article, table))
        product = cursor.fetchone()
        if not product:
            cursor.execute("INSERT INTO products (article, table_name, price) VALUES (%s, %s, %s) RETURNING id", (article, table, price))
            product_id = cursor.fetchone()[0]
        else:
            product_id = product[0]

        # Додавання продукту в корзину
        cursor.execute("""
            INSERT INTO cart (user_id, product_id, quantity, added_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id, product_id) DO UPDATE
            SET quantity = cart.quantity + EXCLUDED.quantity, added_at = NOW()
        """, (user_id, product_id, quantity))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for('index', token=token))
    except Exception as e:
        logging.error(f"Error occurred during adding to cart: {e}")
        return str(e), 500

# Відображення вмісту кошика
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

        # Перевірка на час зберігання товарів в кошику (наприклад, 24 години)
        utc = pytz.UTC
        now = datetime.now(utc)  # Встановлюємо часовий зсув для поточного часу
        for item in cart_items:
            added_at = item[4].replace(tzinfo=utc)  # Встановлюємо часовий зсув для доданого часу
            if now - added_at > timedelta(hours=24):
                cursor.execute("DELETE FROM cart WHERE user_id = %s AND product_id = %s", (user_id, item[5]))
        
        conn.commit()
        cursor.close()
        conn.close()

        return render_template("cart.html", token=token, cart_items=cart_items)
    except Exception as e:
        logging.error(f"Error occurred while viewing cart: {e}")
        return str(e), 500
# Оновлення кількості товарів у кошику
@app.route("/<token>/update_quantity", methods=["POST"])
def update_quantity(token):
    product_id = request.form.get('product_id')
    quantity = int(request.form.get('quantity', 1))

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        user_id = user[0]

        # Оновлення кількості товару в кошику
        cursor.execute("UPDATE cart SET quantity = %s WHERE user_id = %s AND product_id = %s", (quantity, user_id, product_id))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for('view_cart', token=token))
    except Exception as e:
        logging.error(f"Error occurred during updating quantity: {e}")
        return str(e), 500

# Видалення товару з кошика
@app.route("/<token>/remove_item", methods=["POST"])
def remove_item(token):
    product_id = request.form.get('product_id')

