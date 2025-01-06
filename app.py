from flask import Flask, render_template, request
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

@app.route('/search', methods=['POST'])
def search_articles():
    articles_input = request.form.get('articles')
    if not articles_input:
        return render_template('index.html', message="Please enter at least one article.")

    # Розбиваємо введений текст на список артикулів
    articles = [article.strip() for article in articles_input.splitlines() if article.strip()]
    
    if not articles:
        return render_template('index.html', message="No valid articles provided.")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо всі таблиці з price_lists
        cursor.execute("SELECT table_name FROM price_lists")
        tables = cursor.fetchall()

        results = []
        for table in tables:
            table_name = table['table_name']
            query = f"SELECT article, price, %s AS table_name FROM {table_name} WHERE article = ANY(%s)"
            cursor.execute(query, (table_name, articles))
            rows = cursor.fetchall()
            results.extend(rows)

        if results:
            return render_template('index.html', results=results)
        else:
            return render_template('index.html', message="No results found for the provided articles.")

    except Exception as e:
        return render_template('index.html', message=f"Error: {str(e)}")

    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
