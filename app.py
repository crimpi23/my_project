import os
import psycopg2
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from import_data import import_to_db  # Імпортуємо функцію з import_data.py

# Оголошуємо Flask-додаток
app = Flask(__name__)

# Функція для підключення до бази даних
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode='require')

# Головний рут, щоб відображати інтерфейс
@app.route("/")
def index():
    return render_template("index.html")

# Рут для пошуку артикула в базі даних
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
            return jsonify({"error": str(e)}), 500

        return render_template("upload.html", tables=[t[0] for t in tables])

    if request.method == "POST":
        file = request.files.get('file')
        table = request.form.get('table')

        if file and table:
            filename = secure_filename(file.filename)
            file_path = os.path.join('uploads', filename)
            file.save(file_path)

            try:
                # Викликаємо функцію для імпорту в базу
                import_to_db(table, file_path)
                return jsonify({"message": f"Файл {filename} успішно завантажено в таблицю {table}"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Необхідно вибрати файл і таблицю"}), 400

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
