from flask import Flask, request, render_template
import psycopg2

app = Flask(__name__)

# Конфігурація підключення до бази даних PostgreSQL
DB_CONFIG = {
    "host": "dpg-cts5hh5umphs73fk5pvg-a.frankfurt-postgres.render.com",
    "database": "crimpi_parts",
    "user": "crimpi_parts_user",
    "password": "ваш_пароль"
}

@app.route('/', methods=['GET', 'POST'])
def index():
    price = None
    if request.method == 'POST':
        article = request.form.get('article')
        if article:
            # Підключення до бази даних
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM public.vag WHERE article = %s", (article,))
            result = cursor.fetchone()
            if result:
                price = result[0]
            else:
                price = "Артикул не знайдено"
            cursor.close()
            conn.close()
    return render_template('index.html', price=price)

if __name__ == '__main__':
    app.run(debug=True)
