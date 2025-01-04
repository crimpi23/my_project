import os
import psycopg2
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import import_data  # Імпортуємо модуль для обробки файлів

app = Flask(__name__)

# Функція для підключення до бази даних
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode='require')

# Головна сторінка для пошуку артикула
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
        # Отримуємо список таблиць, які вже є в базі
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            tables = cursor.fetchall()
            cursor.close()
            conn.close()
            return render_template("upload.html", tables=[t[0] for t in tables])
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    if request.method == "POST":
        # Завантаження файлу
        table = request.form['table']
        file = request.files['file']

        # Зберігаємо файл
        filename = secure_filename(file.filename)
        file.save(os.path.join("uploads", filename))

        # Викликаємо функцію імпорту даних з файлу
        try:
            import_data.import_to_db(table, os.path.join("uploads", filename))
            return jsonify({"message": "Файл успішно завантажено та оброблено"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
