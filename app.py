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
        elif len(parts) == 2 and parts[0].strip() and parts[1].isdigit():
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

        # Логування SQL-запиту
        print(f"Adding to cart: article={article}, price={price}, quantity={quantity}, table_name={table_name}, user_id={user_id}")

        check_query = """
            SELECT id FROM cart
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products WHERE article = %s AND price = %s AND table_name = %s
            )
        """
        print("Executing query:", check_query % (user_id, article, price, table_name))
        cursor.execute(check_query, (user_id, article, price, table_name))
        existing_cart_item = cursor.fetchone()
        print("Existing cart item:", existing_cart_item)

        if existing_cart_item:
            update_query = """
                UPDATE cart
                SET quantity = quantity + %s
                WHERE id = %s
            """
            print("Executing query:", update_query % (quantity, existing_cart_item['id']))
            cursor.execute(update_query, (quantity, existing_cart_item['id']))
        else:
            insert_query = """
                INSERT INTO cart (user_id, product_id, quantity, added_at)
                VALUES (%s, (SELECT id FROM products WHERE article = %s AND price = %s AND table_name = %s), %s, NOW())
            """
            print("Executing query:", insert_query % (user_id, article, price, table_name, quantity))
            cursor.execute(insert_query, (user_id, article, price, table_name, quantity))
        conn.commit()

        print("Successfully added to cart.")
        return redirect(url_for('index'))
    except Exception as e:
        print("Error in add_to_cart:", e)
        return render_template('index.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()


@app.route('/update_cart', methods=['POST'])
def update_cart():
    try:
        article = request.form.get('article')
        quantity = int(request.form.get('quantity'))
        user_id = 1

        if quantity <= 0:
            return redirect(url_for('remove_from_cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        update_query = """
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products WHERE article = %s
            )
        """
        print("Executing query:", update_query % (quantity, user_id, article))
        cursor.execute(update_query, (quantity, user_id, article))
        conn.commit()
        print(f"Updated cart for user_id={user_id} with article={article}, new quantity={quantity}")

        return redirect(url_for('cart'))
    except Exception as e:
        print("Error in update_cart:", e)
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

        delete_query = """
            DELETE FROM cart
            WHERE user_id = %s AND product_id = (
                SELECT id FROM products WHERE article = %s
            )
        """
        print("Executing query:", delete_query % (user_id, article))
        cursor.execute(delete_query, (user_id, article))
        conn.commit()
        print(f"Removed article={article} from cart for user_id={user_id}")

        return redirect(url_for('cart'))
    except Exception as e:
        print("Error in remove_from_cart:", e)
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    try:
        user_id = 1
        conn = get_db_connection()
        cursor = conn.cursor()

        print(f"Clearing cart for user_id={user_id}")
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()
        print(f"Cart cleared for user_id={user_id}")

        return redirect(url_for('cart'))
    except Exception as e:
        print("Error in clear_cart:", e)
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

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
