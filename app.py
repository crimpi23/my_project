import os
import psycopg2
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from import_data import import_to_db  # Імпортуємо функцію з import_data.py
import asyncio
import aiopg

app = Flask(__name__)

# Підключення до бази даних
async def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL is not set")
    return await aiopg.connect(database_url, sslmode='require')

# Головна сторінка - з пошуком артикула
@app.route("/", methods=["GET"])
async def index():
    article = request.args.get('article')
    error = None
    results = []

    if article:
        try:
            conn = await get_connection()
            cursor = await conn.cursor()

            # Отримуємо всі таблиці прайс-листів
            await cursor.execute("SELECT table_name FROM price_lists")
            tables = await cursor.fetchall()

            # Шукаємо артикул у всіх таблицях
            for table in tables:
                table_name = table[0]
                await cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = %s", (article,))
                rows = await cursor.fetchall()

                if rows:
                    results.append({"table": table_name, "prices": rows})

            await cursor.close()
            await conn.close()

            if not results:
                error = "Артикул не знайдений в жодній таблиці"

        except Exception as e:
            error = str(e)

    return render_template("index.html", article=article, results=results, error=error)

# Рут для завантаження прайс-листів
@app.route("/upload", methods=["GET", "POST"])
async def upload():
    if request.method == "GET":
        try:
            conn = await get_connection()
            cursor = await conn.cursor()
            await cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'vag%'")
            tables = await cursor.fetchall()
            await cursor.close()
            await conn.close()
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
                import_to_db(table, file_path)
                return jsonify({"message": f"Файл {filename} успішно завантажено в таблицю {table}"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Необхідно вибрати файл і таблицю"}), 400

# Рут для пошуку артикулів
@app.route("/search", methods=["GET"])
async def search():
    article = request.args.get('article')

    if not article:
        return jsonify({"error": "Не вказано артикул"}), 400

    try:
        conn = await get_connection()
        cursor = await conn.cursor()

        # Отримуємо всі таблиці прайс-листів
        await cursor.execute("SELECT table_name FROM price_lists")
        tables = await cursor.fetchall()

        results = []

        # Шукаємо артикул у всіх таблицях
        for table in tables:
            table_name = table[0]
            await cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = %s", (article,))
            rows = await cursor.fetchall()

            if rows:
                results.append({"table": table_name, "prices": rows})

        await cursor.close()
        await conn.close()

        if not results:
            return jsonify({"message": "Артикул не знайдений в жодній таблиці"}), 404

        return jsonify({"article": article, "results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Запуск Flask-додатку
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
