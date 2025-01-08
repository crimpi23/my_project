from flask import Flask, render_template, request, session, redirect, url_for, flash
import os
import psycopg2
import psycopg2.extras
import logging
import bcrypt
import csv
import io
from psycopg2.extras import RealDictCursor

import logging
from flask import Flask, render_template, request, session, redirect, url_for, flash
import os
import psycopg2
import psycopg2.extras
import bcrypt

# Налаштування логування (можна додати у верхній частині файлу)
logging.basicConfig(level=logging.DEBUG)

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

# Створення користувача
@app.route('/register', methods=['POST'])
def register():
    try:
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, password_hash) VALUES (%s, %s)
        """, (username, hashed_password.decode('utf-8')))
        conn.commit()

        flash("Registration successful!", "success")
        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Error during registration: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


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
        logging.debug("Grouped results: %s", grouped_results)
        logging.debug("Quantities: %s", quantities)
        logging.debug("Missing articles: %s", missing_articles)

        flash("Search completed successfully!", "success")
        return redirect(url_for('index'))

    except Exception as e:
        logging.error("Error in search_articles: %s", str(e))
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
# Сторінка кошика
@app.route('/cart')
def cart():
    try:
        user_id = 1  # Замінити на логіку реального користувача
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Отримання товарів у кошику
        cursor.execute("""
            SELECT c.product_id, p.article, p.price, c.quantity,
                   (p.price * c.quantity) AS total_price
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        # Логування вмісту кошика
        logging.debug(f"Cart items for user_id={user_id}: {cart_items}")
        for item in cart_items:
            logging.debug(
                f"Cart item: product_id={item['product_id']}, article={item['article']}, "
                f"price={item['price']}, quantity={item['quantity']}, total_price={item['total_price']}"
            )

        # Розрахунок загальної суми
        total_price = sum(item['total_price'] for item in cart_items)
        logging.debug(f"Calculated total_price for cart: {total_price}")

        return render_template('cart.html', cart_items=cart_items, total_price=total_price)
    except Exception as e:
        logging.error(f"Error in cart for user_id={user_id}: {str(e)}", exc_info=True)
        flash("Could not load your cart. Please try again.", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logging.debug("Database connection closed.")


# Додавання в кошик
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    try:
        article = request.form.get('article')
        price = float(request.form.get('price'))
        quantity = int(request.form.get('quantity'))
        table_name = request.form.get('table_name')
        user_id = 1  # Замінити на логіку реального користувача

        conn = get_db_connection()
        cursor = conn.cursor()

        # Перевірка існування товару в таблиці products
        cursor.execute("""
            SELECT id FROM products
            WHERE article = %s AND table_name = %s
        """, (article, table_name))
        product = cursor.fetchone()

        if not product:
            cursor.execute("""
                INSERT INTO products (article, table_name, price)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (article, table_name, price))
            product_id = cursor.fetchone()[0]
        else:
            product_id = product['id']

        # Перевірка наявності товару в кошику
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
        return redirect(request.referrer or url_for('index'))

    except Exception as e:
        logging.error("Error in add_to_cart: %s", str(e))
        flash("Error adding product to cart.", "error")
        return redirect(request.referrer or url_for('index'))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            
# Видалення товару з кошика
@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    conn = None
    cursor = None
    try:
        product_id = request.form.get('product_id')
        user_id = 1  # Замінити на логіку реального користувача

        logging.debug("Received product_id=%s for removal", product_id)

        if not product_id:
            flash("Product ID is missing.", "error")
            return redirect(url_for('cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM cart
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        conn.commit()

        logging.info("Product removed: product_id=%s, user_id=%s", product_id, user_id)
        flash("Product removed from cart.", "success")
        return redirect(url_for('cart'))

    except Exception as e:
        logging.error("Error in remove_from_cart: %s", str(e), exc_info=True)
        flash(f"Error removing product: {str(e)}", "error")
        return redirect(url_for('cart'))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Оновлення товару в кошику
@app.route('/update_cart', methods=['POST'])
def update_cart():
    try:
        product_id = request.form.get('product_id')
        quantity = int(request.form.get('quantity'))
        user_id = 1  # Заміна на реальну логіку ідентифікації користувача

        if not product_id or quantity < 1:
            flash("Invalid product ID or quantity.", "error")
            return redirect(url_for('cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND product_id = %s
        """, (quantity, user_id, product_id))
        conn.commit()

        flash("Cart updated successfully!", "success")
        return redirect(url_for('cart'))

    except Exception as e:
        logging.error("Error updating cart: %s", str(e))
        flash("Error updating cart.", "error")
        return redirect(url_for('cart'))

    finally:
        if cursor:
            cursor.close()
        if conn:
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

        flash("Cart cleared successfully!", "success")
        return redirect(url_for('cart'))
    except Exception as e:
        logging.error("Error clearing cart: %s", str(e))
        flash("Error clearing cart.", "error")
        return redirect(url_for('cart'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Оформлення замовлення
@app.route('/place_order', methods=['POST'])
def place_order():
    try:
        user_id = 1  # Замінити на логіку реального користувача
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримання товарів із кошика
        cursor.execute("""
            SELECT c.product_id, p.price, c.quantity
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        if not cart_items:
            flash("Your cart is empty!", "error")
            logging.error("Cart is empty for user_id=%s", user_id)
            return redirect(url_for('cart'))

        # Логування вмісту кошика
        logging.debug(f"Cart items for user_id={user_id}: {cart_items}")
        for item in cart_items:
            logging.debug(f"Item: product_id={item['product_id']}, price={item['price']}, quantity={item['quantity']}")

        # Розрахунок загальної суми
        total_price = sum(item['price'] * item['quantity'] for item in cart_items)
        logging.debug(f"Calculated total_price for order: {total_price}")

        # Вставка замовлення в таблицю orders
        cursor.execute("""
            INSERT INTO orders (user_id, total_price, order_date)
            VALUES (%s, %s, NOW())
            RETURNING id
        """, (user_id, total_price))
        order_id = cursor.fetchone()['id']
        logging.debug(f"Order created with id={order_id} for user_id={user_id}")

        # Вставка деталей замовлення
        for item in cart_items:
            cursor.execute("""
                INSERT INTO order_details (order_id, product_id, price, quantity, total_price)
                VALUES (%s, %s, %s, %s, %s)
            """, (order_id, item['product_id'], item['price'], item['quantity'], item['price'] * item['quantity']))
            logging.debug(f"Inserted order detail: order_id={order_id}, product_id={item['product_id']}")

        # Очищення кошика
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()

        flash("Order placed successfully!", "success")
        logging.info(f"Order successfully placed for user_id={user_id}")
        return redirect(url_for('cart'))

    except Exception as e:
        conn.rollback()
        logging.error(f"Error placing order for user_id={user_id}: {str(e)}", exc_info=True)
        flash(f"Error placing order: {str(e)}", "error")
        return redirect(url_for('cart'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logging.debug("Database connection closed.")


@app.route('/orders', methods=['GET', 'POST'])
def orders():
    try:
        user_id = 1  # Ідентифікатор користувача
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Пошук за артикулом
        search_article = request.form.get('search_article') if request.method == 'POST' else None

        if search_article:
            # Отримання замовлень, які містять певний артикул
            cursor.execute("""
                SELECT DISTINCT o.id, o.total_price, o.order_date
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                JOIN products p ON od.product_id = p.id
                WHERE o.user_id = %s AND p.article ILIKE %s
                ORDER BY o.order_date DESC
            """, (user_id, f"%{search_article}%"))
        else:
            # Отримання всіх замовлень користувача
            cursor.execute("""
                SELECT id, total_price, order_date
                FROM orders
                WHERE user_id = %s
                ORDER BY order_date DESC
            """, (user_id,))
        
        orders = cursor.fetchall()

        return render_template('orders.html', orders=orders, search_article=search_article)
    except Exception as e:
        flash(f"Error loading orders: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/order_details/<int:order_id>')
def order_details(order_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Отримання деталей замовлення
        cursor.execute("""
            SELECT od.order_id, p.article, p.price, od.quantity, od.total_price
            FROM order_details od
            JOIN products p ON od.product_id = p.id
            WHERE od.order_id = %s
        """, (order_id,))
        details = cursor.fetchall()

        # Логування результатів запиту
        logging.debug(f"Query result for order_id={order_id}: {details}")

        if not details:
            logging.warning(f"No details found for order_id={order_id}")
            flash("No details found for this order.", "warning")
            return render_template('order_details.html', details=[])

        return render_template('order_details.html', details=details)
    except Exception as e:
        logging.error(f"Error loading order details for order_id={order_id}: {str(e)}")
        flash("Error loading order details. Please try again.", "error")
        return redirect(url_for('orders'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/admin')
def admin_panel():
    conn = get_db_connection()
    cursor = conn.cursor()  # DictCursor вже використовується у функції get_db_connection
    
    cursor.execute("""
        SELECT users.id, users.username, users.email
        FROM users
    """)
    users = cursor.fetchall()

    conn.close()
    return render_template('admin_main.html', users=users)



@app.route('/admin/assign_roles', methods=['GET', 'POST'])
def assign_roles():
    conn = get_db_connection()
    cursor = conn.cursor()  # Використовуємо DictCursor за замовчуванням

    # Отримуємо всіх користувачів і їх ролі
    cursor.execute("""
        SELECT users.id AS user_id, users.username, roles.id AS role_id, roles.name AS role_name
        FROM user_roles
        JOIN users ON user_roles.user_id = users.id
        JOIN roles ON user_roles.role_id = roles.id
        ORDER BY users.username;
    """)
    user_roles = cursor.fetchall()  # Результат буде списком об'єктів, подібних до словників

    # Отримуємо всіх користувачів
    cursor.execute("SELECT id, username FROM users;")
    users = cursor.fetchall()

    # Отримуємо всі ролі
    cursor.execute("SELECT id, name FROM roles;")
    roles = cursor.fetchall()

    if request.method == 'POST':
        action = request.form['action']
        user_id = request.form['user_id']
        role_id = request.form['role_id']

        if action == 'assign':
            # Перевіряємо, чи роль уже призначена
            cursor.execute("""
                SELECT * FROM user_roles
                WHERE user_id = %s AND role_id = %s;
            """, (user_id, role_id))
            if cursor.fetchone():
                flash("Role is already assigned to this user.", "warning")
            else:
                # Призначаємо роль
                cursor.execute("""
                    INSERT INTO user_roles (user_id, role_id)
                    VALUES (%s, %s);
                """, (user_id, role_id))
                conn.commit()
                flash("Role assigned successfully.", "success")
        elif action == 'remove':
            # Видаляємо роль у користувача
            cursor.execute("""
                DELETE FROM user_roles
                WHERE user_id = %s AND role_id = %s;
            """, (user_id, role_id))
            conn.commit()
            flash("Role removed successfully.", "success")

        return redirect(url_for('assign_roles'))

    conn.close()
    return render_template('assign_roles.html', user_roles=user_roles, users=users, roles=roles)

# Функція для визначення розділювача
def detect_delimiter(file_content):
    delimiters = [',', ';', '\t', ' ']
    sample_lines = file_content.splitlines()[:5]
    counts = {delimiter: 0 for delimiter in delimiters}

    for line in sample_lines:
        for delimiter in delimiters:
            counts[delimiter] += line.count(delimiter)

    return max(counts, key=counts.get)

@app.route('/admin/upload_price_list', methods=['GET', 'POST'])
def upload_price_list():
    if request.method == 'GET':
        # Отримуємо список таблиць із price_lists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT table_name FROM price_lists;")
        price_lists = cursor.fetchall()
        conn.close()
        return render_template('upload_price_list.html', price_lists=price_lists)

    if request.method == 'POST':
        table_name = request.form['table_name']
        new_table_name = request.form.get('new_table_name', '').strip()

        # Перевіряємо файл
        if 'file' not in request.files:
            flash('No file uploaded', 'error')
            return redirect(url_for('upload_price_list'))

        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('upload_price_list'))

        # Обробляємо файл
        file_content = file.read().decode('utf-8', errors='ignore')
        delimiter = detect_delimiter(file_content)
        reader = csv.reader(io.StringIO(file_content), delimiter=delimiter)

        data = []
        for row in reader:
            if len(row) < 2:
                continue

            article = row[0].strip().replace(" ", "").upper()
            price = row[1].replace(",", ".").strip()

            try:
                price = float(price)
            except ValueError:
                continue

            data.append((article, price))

        conn = get_db_connection()
        cursor = conn.cursor()

        # Якщо обрана нова таблиця
        if table_name == 'new':
            if not new_table_name:
                flash('New table name is required', 'error')
                return redirect(url_for('upload_price_list'))

            # Створюємо нову таблицю
            cursor.execute(f"""
                CREATE TABLE {new_table_name} (
                    article TEXT PRIMARY KEY,
                    price NUMERIC
                );
            """)
            cursor.execute("""
                INSERT INTO price_lists (table_name, created_at)
                VALUES (%s, NOW());
            """, (new_table_name,))

            table_name = new_table_name

        # Очищуємо таблицю перед оновленням
        cursor.execute(f"DELETE FROM {table_name};")

        # Додаємо нові дані
        cursor.executemany(
            f"INSERT INTO {table_name} (article, price) VALUES (%s, %s);", data
        )

        conn.commit()
        conn.close()

        flash(f"Uploaded {len(data)} records to table '{table_name}' successfully.", "success")
        return redirect(url_for('admin_panel'))



if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)