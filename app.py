from flask import Flask, render_template, request, session
import os
import psycopg2
import psycopg2.extras

app = Flask(__name__)

# Генерація secret_key із змінної середовища або автоматичне створення
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Функція для підключення до бази даних
def get_db_connection():
    return psycopg2.connect(
        dsn=os.environ.get('DATABASE_URL'),
        sslmode="require",
        cursor_factory=psycopg2.extras.DictCursor
    )

# Головна сторінка
@app.route('/')
def index():
    return render_template('index.html')

# Пошук артикулів
@app.route('/search', methods=['POST'])
def search_articles():
    articles = []
    quantities = {}
    auto_set_quantities = []
    duplicate_articles = []  # Список для дубльованих артикулів

    # Отримуємо текстовий ввід
    articles_input = request.form.get('articles')
    if not articles_input:
        return render_template('index.html', message="Please enter at least one article.")

    # Розбираємо текстовий ввід на артикули й кількість
    for line in articles_input.splitlines():
        parts = line.strip().split()
        if len(parts) == 1:  # Тільки артикул, без кількості
            article = parts[0].strip()
            if article in quantities:
                quantities[article] += 1
                if article not in duplicate_articles:
                    duplicate_articles.append(article)  # Додаємо до дублювань
            else:
                articles.append(article)
                quantities[article] = 1
                auto_set_quantities.append(article)
        elif len(parts) == 2 and parts[0].strip() and parts[1].isdigit():  # Артикул і кількість
            article, quantity = parts
            if article in quantities:
                quantities[article] += int(quantity)
                if article not in duplicate_articles:
                    duplicate_articles.append(article)  # Додаємо до дублювань
            else:
                articles.append(article)
                quantities[article] = int(quantity)

    if not articles:
        return render_template('index.html', message="No valid articles provided.")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

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

        # Зберігаємо результати пошуку в сесії
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

        # Перевіряємо, чи запис існує
        cursor.execute("""
            SELECT id FROM cart
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products
                WHERE article = %s AND price = %s AND table_name = %s
            )
        """, (user_id, article, price, table_name))
        existing_cart_item = cursor.fetchone()

        if existing_cart_item:
            cursor.execute("""
                UPDATE cart
                SET quantity = quantity + %s
                WHERE id = %s
            """, (quantity, existing_cart_item['id']))
        else:
            cursor.execute("""
                INSERT INTO cart (user_id, product_id, quantity, added_at)
                VALUES (%s, (SELECT id FROM products WHERE article = %s AND price = %s AND table_name = %s), %s, NOW())
            """, (user_id, article, price, table_name, quantity))
        conn.commit()

        grouped_results = session.get('grouped_results', {})
        quantities = session.get('quantities', {})

        return render_template(
            'index.html',
            grouped_results=grouped_results,
            quantities=quantities,
            message="Product added to cart successfully!"
        )
    except Exception as e:
        return render_template('index.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@app.route('/cart')
def view_cart():
    try:
        user_id = 1  # Заставний користувач
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо всі товари з кошика
        cursor.execute("""
            SELECT c.id AS cart_id, p.article, p.price, c.quantity, c.product_id
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

@app.route('/update_cart', methods=['POST'])
def update_cart():
    try:
        cart_id = request.form.get('cart_id')
        quantity = int(request.form.get('quantity'))

        conn = get_db_connection()
        cursor = conn.cursor()

        if quantity > 0:
            # Оновлюємо кількість у кошику
            cursor.execute("""
                UPDATE cart
                SET quantity = %s
                WHERE id = %s
            """, (quantity, cart_id))
        else:
            # Видаляємо товар із кошика, якщо кількість 0
            cursor.execute("""
                DELETE FROM cart
                WHERE id = %s
            """, (cart_id,))

        conn.commit()
        return view_cart()

    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
