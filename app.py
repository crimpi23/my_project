import os
import tempfile
import psycopg2
import uuid
from flask import Flask, request, render_template, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
from import_data import import_to_db  # Імпортуємо функцію з import_data.py
import logging

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
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, product_id) DO UPDATE SET quantity = cart.quantity + EXCLUDED.quantity", (user_id, product_id, quantity))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for('index', token=token))
    except Exception as e:
        logging.error(f"Error occurred during adding to cart: {e}")
        return str(e), 500

# Рут для завантаження прайс-листів
@app.route("/upload", methods=["GET", "POST"])
def upload():
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
        return render_template("upload.html", tables=[t[0] for t in tables])

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
                logging.error(f"Error occurred during import: {e}")
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Необхідно вибрати файл і таблицю"}), 400

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
