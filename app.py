from flask import Flask, render_template, request, session, redirect, url_for
import os
import psycopg2
import psycopg2.extras

app = Flask(__name__)

# Секретний ключ для сесій
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Функція для підключення до бази даних
def get_db_connection():
    return psycopg2.connect(
        dsn=os.environ.get('DATABASE_URL'),
        sslmode="require",
        cursor_factory=psycopg2.extras.DictCursor
    )

# Головна сторінка для пошуку
@app.route('/')
def index():
    grouped_results = session.get('grouped_results', {})
    quantities = session.get('quantities', {})
    missing_articles = session.get('missing_articles', [])
    auto_set_quantities = session.get('auto_set_quantities', [])
    duplicate_articles = session.get('duplicate_articles', [])

    return render_template(
        'index.html',
        grouped_results=grouped_results,
        quantities=quantities,
        missing_articles=missing_articles,
        auto_set_quantities=auto_set_quantities,
        duplicate_articles=duplicate_articles
    )

# Маршрут для пошуку артикулів
@app.route('/search', methods=['POST'])
def search_articles():
    articles = []
    quantities = {}
    auto_set_quantities = []
    duplicate_articles = []

    # Обробка введення
    articles_input = request.form.get('articles')
    if not articles_input:
        return render_template('index.html', message="Please enter at least one article.")

    for line in articles_input.splitlines():
        parts = line.strip().split()
        if len(parts) == 1:  # Тільки артикул
            article = parts[0].strip()
            if article in quantities:
                quantities[article] += 1
                if article not in duplicate_articles:
                    duplicate_articles.append(article)
            else:
                articles.append(article)
                quantities[article] = 1
                auto_set_quantities.append(article)
        elif len(parts) == 2 and parts[0].strip() and parts[1].isdigit():  # Артикул і кількість
            article, quantity = parts
            if article in quantities:
                quantities[article] += int(quantity)
                if article not in duplicate_articles:
                    duplicate_articles.append(article)
            else:
                articles.append(article)
                quantities[article] = int(quantity)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо таблиці
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

        grouped_results = {}
        for result in results:
            article = result['article']
            if article not in grouped_results:
                grouped_results[article] = []
            grouped_results[article].append({
                'price': result['price'],
                'table_name': result['table_name']
            })

        missing_articles = [article for article in articles if article not in grouped_results]

        session['grouped_results'] = grouped_results
        session['quantities'] = quantities

        return render_template(
            'index.html',
            grouped_results=grouped_results,
            quantities=quantities,
            missing_articles=missing_articles,
            auto_set_quantities=auto_set_quantities,
            duplicate_articles=duplicate_articles
        )

    except Exception as e:
        return render_template('index.html', message=f"Error: {str(e)}")

    finally:
        cursor.close()
        conn.close()

# Сторінка кошика
@app.route('/cart')
def cart():
    try:
        user_id = 1
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT p.article, p.price, c.quantity, (p.price * c.quantity) AS total_price, p.table_name
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        return render_template('cart.html', cart_items=cart_items)
    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Додавання в кошик
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    try:
        article = request.form.get('article')
        price = float(request.form.get('price'))
        quantity = int(request.form.get('quantity'))
        table_name = request.form.get('table_name')
        user_id = 1

        conn = get_db_connection()
        cursor = conn.cursor()

        # Перевіряємо, чи товар уже є в кошику
        cursor.execute("""
            SELECT id FROM cart
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products WHERE article = %s AND price = %s AND table_name = %s
            )
        """, (user_id, article, price, table_name))
        existing_cart_item = cursor.fetchone()

        if existing_cart_item:
            # Оновлюємо кількість
            cursor.execute("""
                UPDATE cart
                SET quantity = quantity + %s
                WHERE id = %s
            """, (quantity, existing_cart_item['id']))
        else:
            # Додаємо новий товар
            cursor.execute("""
                INSERT INTO cart (user_id, product_id, quantity, added_at)
                VALUES (%s, (SELECT id FROM products WHERE article = %s AND price = %s AND table_name = %s), %s, NOW())
            """, (user_id, article, price, table_name, quantity))
        conn.commit()

        return redirect(url_for('index'))
    except Exception as e:
        return render_template('index.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Оновлення кошика
@app.route('/update_cart', methods=['POST'])
def update_cart():
    try:
        article = request.form.get('article')
        quantity = int(request.form.get('quantity'))
        user_id = 1

        if quantity <= 0:
            # Якщо кількість <= 0, видаляємо товар
            return redirect(url_for('remove_from_cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        # Оновлюємо кількість товару
        cursor.execute("""
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products WHERE article = %s
            )
        """, (quantity, user_id, article))
        conn.commit()

        return redirect(url_for('cart'))  # Повертаємося на кошик
    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    try:
        article = request.form.get('article')
        user_id = 1

        conn = get_db_connection()
        cursor = conn.cursor()

        # Видаляємо товар із кошика
        cursor.execute("""
            DELETE FROM cart
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products WHERE article = %s
            )
        """, (user_id, article))
        conn.commit()

        return redirect(url_for('cart'))  # Повертаємося на кошик
    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # Порт, визначений середовищем Render
    app.run(host='0.0.0.0', port=port, debug=True)