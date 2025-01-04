import os
import psycopg2
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Додаємо шлях до бібліотеки вручну
#os.add_dll_directory(r"C:\Program Files\PostgreSQL\17\bin")

# Функція для підключення до бази
def get_connection():
    return psycopg2.connect(
        host="dpg-cts5hh5umphs73fk5pvg-a.frankfurt-postgres.render.com",
        database="crimpi_parts",
        user="crimpi_parts_user",
        password="m9xEi6jMGGtDrtYMh8P3oW3zR6RLFTWn"
    )

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search", methods=["GET"])
def search():
    article = request.args.get("article")
    if not article:
        return jsonify({"error": "Введіть артикул"}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM public.vag WHERE article = %s;", (article,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return jsonify({"article": article, "price": float(result[0])})
        else:
            return jsonify({"error": f"Артикул {article} не знайдено"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
