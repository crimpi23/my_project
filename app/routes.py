# app/routes.py

from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from .forms import ArticleForm, UploadForm
from .utils import get_connection, release_connection, import_to_db
import logging

bp = Blueprint('main', __name__)

logging.basicConfig(level=logging.DEBUG)

@bp.route("/", methods=["GET"])
def home():
    return redirect(url_for('main.index', token='default'))

@bp.route("/<token>/", methods=["GET", "POST"])
def index(token):
    form = ArticleForm()
    results = []
    if form.validate_on_submit():
        article = form.article.data.replace(" ", "")  # Видаляємо пробіли
        articles = form.articles.data.replace(" ", "") if form.articles.data else ""
        results = search_articles(token, article, articles)
    return render_template('index.html', form=form, token=token, results=results)

def search_articles(token, article, articles):
    conn = get_connection()
    cursor = conn.cursor()
    results = {}
    
    # Запити до бази даних
    try:
        # Перевірка валідності токена
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return "Invalid token", 403

        user_id = user[0]

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
        
        if articles:
            articles_list = [a.strip().replace(" ", "") for a in articles.split('\n') if a.strip()]

            # Отримуємо всі таблиці прайс-листів
            cursor.execute("SELECT table_name FROM price_lists")
            tables = cursor.fetchall()

            # Шукаємо артикули у всіх таблицях
            for table in tables:
                table_name = table[0]
                cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = ANY(%s::text[])", (articles_list,))
                rows = cursor.fetchall()

                for row in rows:
                    article = row[0]
                    if article not in results:
                        results[article] = []
                    results[article].append({"table": table_name, "price": row[1]})

    except Exception as e:
        logging.error(f"Error occurred during search: {e}")

    finally:
        cursor.close()
        release_connection(conn)

    return results

@bp.route("/<token>/add_to_cart", methods=["POST"])
def add_to_cart(token):
    article = request.form.get('article')
    table = request.form.get('table')
    price = request.form.get('price')
    quantity = int(request.form.get('quantity', 1))

    # Отримуємо результати пошуку з форми і конвертуємо до словника
    results_str = request.form.get('results')
    results = eval(results_str) if results_str else {}

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
        release_connection(conn)

        return redirect(url_for('main.index', token=token, results=results))  # Повертаємо результати пошуку
    except Exception as e:
        logging.error(f"Error occurred during adding to cart: {e}")
        return str(e), 500
