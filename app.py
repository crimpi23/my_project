from flask import Flask, render_template, request, session, redirect, url_for, flash
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
    return render_template(
        'index.html',
        grouped_results=session.get('grouped_results', {}),
        quantities=session.get('quantities', {}),
        missing_articles=session.get('missing_articles', []),
        auto_set_quantities=session.get('auto_set_quantities', []),
        duplicate_articles=session.get('duplicate_articles', [])
    )

# Маршрут для пошуку артикулів
@app.route('/search', methods=['POST'])
def search_articles():
    try:
        articles = []
        quantities = {}
        auto_set_quantities = []
        duplicate_articles = []

        articles_input = request.form.get('articles')
        if not articles_input:
            flash("Please enter at least one article.", "error")
            return redirect(url_for('index'))

        for line in articles_input.splitlines():
            parts = line.strip().split()
            if len(parts) == 1:
                article = parts[0].strip()
                if article in quantities:
                    quantities[article] += 1
                    if article not in duplicate_articles:
                        duplicate_articles.append(article)
                else:
                    articles.append(article)
                    quantities[article] = 1
                    auto_set_quantities.append(article)
            elif len(parts) == 2 and parts[1].isdigit():
                article, quantity = parts
                if article in quantities:
                    quantities[article] += int(quantity)
                    if article not in duplicate_articles:
                        duplicate_articles.append(article)
                else:
                    articles.append(article)
                    quantities[article] = int(quantity)

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
            results.extend(cursor.fetchall())

        grouped_results = {}
        for result in results:
            article = result['article']
            grouped_results.setdefault(article, []).append({
                'price': result['price'],
                'table_name': result['table_name']
            })

        missing_articles = [article for article in articles if article not in grouped_results]

        # Збереження результатів у сесії
        session['grouped_results'] = grouped_results
        session['quantities'] = quantities
        session['missing_articles'] = missing_articles

        # Логування діагностики
        print("Grouped results:", grouped_results)
        print("Quantities:", quantities)
        print("Missing articles:", missing_articles)

        flash("Search completed successfully!", "success")
        return redirect(url_for('index'))

    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('index'))
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

        # Отримуємо товари з кошика
        cursor.execute("""
            SELECT p.article, p.price, c.quantity, (p.price * c.quantity) AS total_price, p.table_name
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        # Логування даних
        print("Fetched cart items:", cart_items)

        # Передаємо дані до шаблону
        return render_template('cart.html', cart_items=cart_items)
    except Exception as e:
        # Логуємо помилку
        print(f"Error in cart function: {e}")
        flash("Could not load your cart. Please try again.", "error")
        return redirect(url_for('index'))
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

        cursor.execute("""
            SELECT id FROM products
            WHERE article = %s AND price = %s AND table_name = %s
        """, (article, price, table_name))
        product = cursor.fetchone()

        if not product:
            flash("Product not found in database.", "error")
            return redirect(url_for('index'))

        product_id = product['id']

        cursor.execute("""
            SELECT id FROM cart
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
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
                VALUES (%s, %s, %s, NOW())
            """, (user_id, product_id, quantity))

        conn.commit()

        flash("Product added to cart!", "success")
        return redirect(url_for('cart'))
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        cursor.close()
        conn.close()

# Видалення товару з кошика
@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    try:
        product_id = request.form.get('product_id')
        user_id = 1  # Замініть на реальну логіку ідентифікації користувача

        if not product_id:
            flash("Product ID is missing.", "error")
            return redirect(url_for('cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        # Видаляємо конкретний товар з кошика
        cursor.execute("""
            DELETE FROM cart
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        conn.commit()

        flash("Product removed from cart.", "success")
        return redirect(url_for('cart'))

    except Exception as e:
        flash(f"Error removing product: {str(e)}", "error")
        return redirect(url_for('cart'))

    finally:
        cursor.close()
        conn.close()

@app.route('/update_cart', methods=['POST'])
def update_cart():
    try:
        article = request.form.get('article')
        quantity = int(request.form.get('quantity'))
        user_id = 1

        # Отримуємо product_id
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM products WHERE article = %s
        """, (article,))
        product = cursor.fetchone()

        if not product:
            return render_template('cart.html', message="Product not found in database.")

        product_id = product['id']

        # Оновлюємо кількість
        cursor.execute("""
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND product_id = %s
        """, (quantity, user_id, product_id))
        conn.commit()

        return redirect(url_for('cart'))
    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Очищення кошика
@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    try:
        user_id = 1
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()

        return redirect(url_for('cart'))
    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Оформлення замовлення
@app.route('/place_order', methods=['POST'])
def place_order():
    try:
        user_id = 1
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("INSERT INTO orders (user_id) VALUES (%s) RETURNING id", (user_id,))
        order_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO order_details (order_id, product_id, price, quantity)
            SELECT %s, c.product_id, p.price, c.quantity
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (order_id, user_id))

        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()

        return render_template('cart.html', message="Order placed successfully!")
    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)