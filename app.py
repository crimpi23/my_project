import os
import psycopg2
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from import_data import import_to_db  # Імпортуємо функцію з import_data.py

app = Flask(__name__)

# Підключення до бази даних
def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode='require')

# Перевірка та створення директорії для завантажених файлів
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Головна сторінка - без пошуку артикула при завантаженні
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

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
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            try:
                # Збереження файлу
                file.save(file_path)

                # Імпорт даних в базу
                import_to_db(table, file_path)
                return jsonify({"message": f"Файл {filename} успішно завантажено в таблицю {table}"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Необхідно вибрати файл і таблицю"}), 400

# Рут для пошуку артикулів
@app.route("/search", methods=["GET"])
def search():
    article = request.args.get('article')

    if not article:
        return jsonify({"error": "Не вказано артикул"}), 400

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT table_name FROM price_lists")
        tables = cursor.fetchall()

        results = []

        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = %s", (article,))
            rows = cursor.fetchall()

            if rows:
                results.append({"table": table_name, "prices": rows})

        cursor.close()
        conn.close()

        if not results:
            return jsonify({"message": "Артикул не знайдений в жодній таблиці"}), 404

        return jsonify({"article": article, "results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
