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
    articles = []
    quantities = {}

    # Отримуємо текстовий ввід
    articles_input = request.form.get('articles')
    if not articles_input:
        return render_template('index.html', message="Please enter at least one article and quantity.")

    # Розбираємо текстовий ввід на артикули й кількість
    for line in articles_input.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[0].strip() and parts[1].isdigit():
            article, quantity = parts
            articles.append(article.strip())
            quantities[article] = int(quantity)

    # Якщо немає валідних даних
    if not articles:
        return render_template('index.html', message="No valid articles provided. Please enter Article and Quantity separated by a space.")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо всі таблиці з price_lists
        cursor.execute("SELECT table_name FROM price_lists")
        tables = cursor.fetchall()

        results = []
        for table in tables:
            table_name = table['table_name']
            query = f"""
                SELECT article, price, %s AS table_name
                FROM {table_name}
                WHERE article = ANY(%s)
            """
            cursor.execute(query, (table_name, articles))
            rows = cursor.fetchall()
            results.extend(rows)

        # Сортуємо результати відповідно до порядку введених артикулів
        sorted_results = sorted(
            results,
            key=lambda x: articles.index(x['article'])
        )

        # Визначаємо артикули, яких немає в результатах
        found_articles = {result['article'] for result in results}
        missing_articles = [article for article in articles if article not in found_articles]

        if sorted_results or missing_articles:
            return render_template(
                'index.html',
                results=sorted_results,
                quantities=quantities,
                missing_articles=missing_articles
            )
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
