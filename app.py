from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os

# Ініціалізація Flask
app = Flask(__name__)

# Підключення до бази даних через DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")

# Функція для підключення до бази даних
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

@app.route('/')
def home():
    return "API для пошуку цін за артикулами. Використовуйте /search?article=ARTICUL"

@app.route('/search', methods=['GET'])
def search_article():
    article = request.args.get('article')
    if not article:
        return jsonify({"error": "Параметр 'article' обов'язковий"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо список таблиць з price_lists
        cursor.execute("SELECT table_name FROM price_lists")
        tables = cursor.fetchall()

        results = []
        for table in tables:
            table_name = table['table_name']
            query = f"SELECT article, price FROM {table_name} WHERE article = %s"
            cursor.execute(query, (article,))
            rows = cursor.fetchall()
            results.extend(rows)

        if results:
            return jsonify({"article": article, "prices": results})
        else:
            return jsonify({"article": article, "message": "Артикул не знайдено"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

# Запуск сервера
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
