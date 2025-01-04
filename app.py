import os
import psycopg2
from flask import Flask, request, jsonify, render_template

# Оголошуємо Flask-додаток
app = Flask(__name__)

# Функція для підключення до бази даних
def get_connection():
    # Отримуємо DATABASE_URL із середовища
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        raise Exception("DATABASE_URL is not set")
    
    # Підключаємося до PostgreSQL через psycopg2 з параметром SSL
    return psycopg2.connect(database_url, sslmode='require')

# Головний рут, щоб відображати інтерфейс
@app.route("/")
def index():
    return render_template("index.html")

# Рут для пошуку артикула в базі даних
@app.route("/search", methods=["GET"])
def search():
    article = request.args.get("article")
    
    # Перевірка, чи передано артикул
    if not article:
        return jsonify({"error": "Введіть артикул"}), 400

    try:
        # Підключення до бази даних
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM public.vag WHERE article = %s;", (article,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        # Перевірка наявності ціни для артикула
        if result:
            return jsonify({"article": article, "price": float(result[0])})
        else:
            return jsonify({"error": f"Артикул {article} не знайдено"}), 404
    except Exception as e:
        # Якщо сталася помилка, повертаємо повідомлення про помилку
        return jsonify({"error": str(e)}), 500

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
