from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os

app = Flask(__name__)

# Підключення до бази даних
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['GET'])
def search_article():
    article = request.args.get('article')
    if not article:
        return render_template('index.html', message="Please enter an article.")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо всі таблиці з price_lists
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
            return render_template('index.html', prices=results)
        else:
            return render_template('index.html', message="No results found for the given article.")

    except Exception as e:
        return render_template('index.html', message=f"Error: {str(e)}")

    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
