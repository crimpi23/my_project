import os
import psycopg2
from flask import Flask, request, render_template, jsonify
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
@app.route("/", methods=["GET"])
def index():
    article = request.args.get('article')
    articles = request.args.get('articles')
    error = None
    results = {}

    try:
        conn = get_connection()
        cursor = conn.cursor()

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

    return render_template("index.html", article=article, articles=articles, results=results, error=error)

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
