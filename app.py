from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify, send_file
import os
import psycopg2
import psycopg2.extras
import logging
import csv
import io
import bcrypt
from functools import wraps

# Налаштування логування
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Секретний ключ для сесій
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))


# Генерує унікальний токен для користувача
def generate_token():
    return os.urandom(16).hex()


# Хешує пароль для збереження у базі даних
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


# Перевіряє відповідність пароля хешу з бази
def verify_password(stored_hash, password):
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))


# Функція для підключення до бази даних
def get_db_connection():
    return psycopg2.connect(
        dsn=os.environ.get('DATABASE_URL'),
        sslmode="require",
        cursor_factory=psycopg2.extras.DictCursor
    )


# Головна сторінка за токеном
@app.route('/<token>/')
def token_index(token):
    role = validate_token(token)
    if not role:
        flash("Invalid token.", "error")
    return redirect(request.referrer or url_for('simple_search'))

    # Збереження токена та ролі у сесії
    session['token'] = token
    session['role'] = role
    return render_template('index.html', role=role)


# Запит про токен / Перевірка токена / Декоратор для перевірки токена
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = session.get('token')
        if not token:
            flash("Access denied. Token is required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# Головна сторінка з перевіркою токена
@app.route('/')
def index():
    token = session.get('token')
    if not token:
        return render_template('simple_search.html')
    role = validate_token(token)
    return render_template('index.html', role=role)


# Пошук для користувачів без токену
@app.route('/simple_search', methods=['GET', 'POST'])
def simple_search():
    if request.method == 'POST':
        article = request.form.get('article')
        if not article:
            flash("Please enter an article for search.", "error")
            return redirect(url_for('simple_search'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT article, price FROM articles_table  -- Замініть на вашу таблицю
                WHERE article = %s
            """, (article,))
            results = cursor.fetchall()
        except Exception as e:
            logging.error(f"Error in simple_search: {e}")
            flash("An error occurred during the search.", "error")
            results = []
        finally:
            if 'conn' in locals():
                conn.close()

        if not results:
            flash("No results found for your search.", "info")
        return render_template('simple_search_results.html', results=results)
    return render_template('simple_search.html')




# Доступ до адмін-панелі:
@app.route('/admin', methods=['GET', 'POST'])
@app.route('/<token>/admin', methods=['GET', 'POST'])
def admin_panel(token=None):
    try:
        # Перевірка токена, якщо передано
        if token:
            logging.debug(f"Token received: {token}")
            role = validate_token(token)
            if not role or role != "admin":
                logging.warning(f"Access denied for token: {token}")
                flash("Access denied. Admin rights are required.", "error")
                return redirect(request.referrer or url_for('index'))
            session['token'] = token  # Зберігаємо токен у сесії

        if request.method == 'POST':
            # Обробка введеного пароля
            password = request.form.get('password')
            if not password:
                flash("Password is required.", "error")
                return redirect(url_for('admin_panel', token=token))

            # Підключення до бази даних
            conn = get_db_connection()
            cursor = conn.cursor()

            # Отримання хеша пароля адміністратора
            cursor.execute("""
                SELECT password_hash 
                FROM users 
                WHERE id IN (
                    SELECT user_id 
                    FROM user_roles 
                    WHERE role_id = 1 -- Підставляємо ID ролі адміністратора
                );
            """)
            admin_password_hash = cursor.fetchone()

            logging.debug(f"Fetched password hash: {admin_password_hash}")

            # Перевірка хеша пароля
            if not admin_password_hash or not verify_password(admin_password_hash[0], password):
                logging.warning("Invalid admin password attempt.")
                flash("Invalid password.", "error")
                return redirect(url_for('admin_panel', token=token))

            # Аутентифікація успішна
            session['admin_authenticated'] = True
            logging.info("Admin successfully authenticated.")
            return redirect(url_for('admin_dashboard', token=token))

        # Якщо метод GET, показати форму логіну
        return render_template('admin_login.html', token=token)

    except Exception as e:
        logging.error(f"Error in admin_panel: {e}", exc_info=True)
        flash("An error occurred while accessing the admin panel.", "error")
        return redirect(url_for('index'))

    finally:
        if 'conn' in locals() and conn:
            conn.close()





# Це треба потім описати, теж щось про адмінку
@app.route('/<token>/admin/dashboard', methods=['GET'])
@token_required
def admin_dashboard(token):
    role = validate_token(token)
    if not role or role != "admin":
        flash("Access denied.", "error")
        return redirect(request.referrer or url_for('token_index', token=token))

    if not session.get('admin_authenticated'):
        flash("Password is required for admin access.", "error")
        return redirect(request.referrer or url_for('admin_panel', token=token))

    return render_template('admin_main.html')


# Функція для перевірки токена
def validate_token(token):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.name AS role
            FROM tokens t
            JOIN user_roles ur ON ur.user_id = t.user_id
            JOIN roles r ON ur.role_id = r.id
            WHERE t.token = %s
        """, (token,))
        result = cursor.fetchone()
        conn.close()
        return result['role'] if result else None
    except Exception as e:
        logging.error(f"Error validating token: {e}")
        return None


# Створення користувача в адмін панелі:
# Створення користувача в адмін-панелі
@app.route('/<token>/admin/create_user', methods=['GET', 'POST'])
@token_required
def create_user(token):
    role = validate_token(token)
    if not role or role != "admin":
        flash("Access denied. Admin rights are required.", "error")
        return redirect(request.referrer or url_for('token_index', token=token))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role_id = request.form.get('role_id')

        if not username or not password or not role_id:
            flash("All fields are required.", "error")
            return redirect(request.referrer or url_for('create_user', token=token))

        hashed_password = hash_password(password)
        user_token = generate_token()

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users (username, password_hash)
                VALUES (%s, %s)
                RETURNING id
            """, (username, hashed_password))
            user_id = cursor.fetchone()['id']

            cursor.execute("""
                INSERT INTO user_roles (user_id, role_id, assigned_at)
                VALUES (%s, %s, NOW())
            """, (user_id, role_id))

            cursor.execute("""
                INSERT INTO tokens (user_id, token)
                VALUES (%s, %s)
            """, (user_id, user_token))

            conn.commit()
            flash(f"User created successfully! Token: {user_token}", "success")
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating user: {e}")
            flash("Error creating user.", "error")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        return redirect(request.referrer or url_for('create_user', token=token))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM roles")
    roles = cursor.fetchall()
    conn.close()

    return render_template('create_user.html', roles=roles, token=token)


# Маршрут для пошуку артикулів
@app.route('/search', methods=['POST'])
def search_articles():
    try:
        articles = []
        quantities = {}
        auto_set_quantities = []
        duplicate_articles = []
        missing_articles = []  # Ініціалізуємо список

        articles_input = request.form.get('articles')
        if not articles_input:
            flash("Please enter at least one article.", "error")
            return redirect(request.referrer or url_for('index'))

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
        logging.debug(f"Articles to search: {articles}")
        logging.debug(f"Quantities: {quantities}")
        logging.debug(f"Grouped results: {grouped_results}")

        flash("Search completed successfully!", "success")
        return redirect(request.referrer or url_for('index'))

    except Exception as e:
        logging.error("Error in search_articles: %s", str(e))
        flash(f"Error: {str(e)}", "error")
        return redirect(request.referrer or url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/clear_search', methods=['POST'])
def clear_search():
    try:
        logging.debug("Clearing search data from session.")
        session.pop('grouped_results', None)
        session.pop('quantities', None)
        session.pop('missing_articles', None)
        flash("Search data cleared successfully.", "success")
    except Exception as e:
        logging.error(f"Error clearing search data: {str(e)}", exc_info=True)
        flash("Could not clear search data. Please try again.", "error")
    return redirect(request.referrer or url_for('index'))


# Сторінка кошика
@app.route('/cart', methods=['GET'])
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

        # Розрахунок загальної суми
        total_price = sum(item['total_price'] for item in cart_items)

        # Очищення непотрібних флеш-повідомлень
        session.pop('grouped_results', None)
        session.pop('quantities', None)
        session.pop('missing_articles', None)

        return render_template('cart.html', cart_items=cart_items, total_price=total_price)

    except Exception as e:
        logging.error(f"Error in cart for user_id={user_id}: {str(e)}", exc_info=True)
        flash("Could not load your cart. Please try again.", "error")
        return redirect(request.referrer or url_for('index'))
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

        logging.debug(f"Adding to cart: Article={article}, Price={price}, Quantity={quantity}, Table={table_name}, User={user_id}")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Перевірка існування товару
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
            logging.info(f"New product added: ID={product_id}")
        else:
            product_id = product['id']
            logging.debug(f"Product already exists: ID={product_id}")

        # Додавання або оновлення товару в кошику
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
            logging.info(f"Cart updated for product ID={product_id}, Quantity={quantity}")
        else:
            cursor.execute("""
                INSERT INTO cart (user_id, product_id, quantity, added_at)
                VALUES (%s, %s, %s, NOW())
            """, (user_id, product_id, quantity))
            logging.info(f"Product added to cart: Product ID={product_id}, Quantity={quantity}")

        conn.commit()
        flash("Product added to cart!", "success")
        return redirect(request.referrer or url_for('index'))

    except Exception as e:
        logging.error(f"Error in add_to_cart: {e}", exc_info=True)
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
            return redirect(request.referrer or url_for('cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM cart
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        conn.commit()

        logging.info("Product removed: product_id=%s, user_id=%s", product_id, user_id)
        flash("Product removed from cart.", "success")
        return redirect(request.referrer or url_for('cart'))

    except Exception as e:
        logging.error("Error in remove_from_cart: %s", str(e), exc_info=True)
        flash(f"Error removing product: {str(e)}", "error")
        return redirect(request.referrer or url_for('cart'))

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
            return redirect(request.referrer or url_for('cart'))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND product_id = %s
        """, (quantity, user_id, product_id))
        conn.commit()

        flash("Cart updated successfully!", "success")
        return redirect(request.referrer or url_for('cart'))

    except Exception as e:
        logging.error("Error updating cart: %s", str(e))
        flash("Error updating cart.", "error")
        return redirect(request.referrer or url_for('cart'))

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
        return redirect(request.referrer or url_for('cart'))
    except Exception as e:
        logging.error("Error clearing cart: %s", str(e))
        flash("Error clearing cart.", "error")
        return redirect(request.referrer or url_for('cart'))
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
            return redirect(request.referrer or url_for('cart'))

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
        return redirect(request.referrer or url_for('cart'))

    except Exception as e:
        conn.rollback()
        logging.error(f"Error placing order for user_id={user_id}: {str(e)}", exc_info=True)
        flash(f"Error placing order: {str(e)}", "error")
        return redirect(request.referrer or url_for('cart'))
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
        return redirect(request.referrer or url_for('index'))
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
        return redirect(request.referrer or url_for('orders'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


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

        return redirect(request.referrer or url_for('assign_roles'))

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


# Завантаження прайсу в Адмінці
@app.route('/admin/upload_price_list', methods=['GET', 'POST'])
def upload_price_list():
    if request.method == 'GET':
        try:
            flash("This is a test message.", "success")  # Тестове повідомлення
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM price_lists;")
            price_lists = cursor.fetchall()
            conn.close()
            logging.info("Price list tables fetched successfully.")
            # "Споживаємо" всі Flash-повідомлення після завантаження сторінки
            get_flashed_messages(with_categories=True)
            return render_template('upload_price_list.html', price_lists=price_lists)
        except Exception as e:
            logging.error(f"Error during GET request: {str(e)}")
            return {"status": "error", "message": "Error loading the page."}, 500

    if request.method == 'POST':
        try:
            logging.info("Starting file upload process.")
            start_time = time.time()  # Початок вимірювання часу

            # Отримання таблиці та файлу
            table_name = request.form['table_name']
            new_table_name = request.form.get('new_table_name', '').strip()
            file = request.files.get('file')

            if not file or file.filename == '':
                logging.error("No file uploaded or selected.")
                flash("No file uploaded or selected.", "error")
                return redirect(request.referrer or url_for('upload_price_list'))

            # Обробка файлу
            file_content = file.read().decode('utf-8', errors='ignore')
            delimiter = detect_delimiter(file_content)
            reader = csv.reader(io.StringIO(file_content), delimiter=delimiter)
            data = []

            header_skipped = False
            for row in reader:
                if len(row) < 2:
                    logging.warning(f"Skipping invalid row: {row}")
                    continue
                if not header_skipped and not row[1].replace(',', '').replace('.', '').isdigit():
                    logging.info(f"Skipping header row: {row}")
                    header_skipped = True
                    continue
                article = row[0].strip().replace(" ", "").upper()
                try:
                    price = float(row[1].replace(",", ".").strip())
                    data.append((article, price))
                except ValueError:
                    logging.warning(f"Skipping row with invalid price: {row}")
                    continue

            logging.info(f"Number of rows prepared: {len(data)}")

            # Підключення до бази даних
            conn = get_db_connection()
            cursor = conn.cursor()

            # Якщо створюємо нову таблицю
            if table_name == 'new':
                if not new_table_name:
                    logging.error("New table name is missing.")
                    flash("New table name is required.", "error")
                    return redirect(request.referrer or url_for('upload_price_list'))
                table_name = new_table_name.strip().replace(" ", "_").lower()
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        article TEXT PRIMARY KEY,
                        price NUMERIC
                    );
                """)
                cursor.execute("""
                    INSERT INTO price_lists (table_name, created_at)
                    VALUES (%s, NOW());
                """, (table_name,))
                conn.commit()

            # Очищення таблиці
            logging.info(f"Truncating table: {table_name}")
            cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY;")
            conn.commit()

            # Імпорт через COPY
            logging.info(f"Starting COPY into table: {table_name}")
            output = io.StringIO()
            for row in data:
                output.write(f"{row[0]},{row[1]}\n")
            output.seek(0)
            cursor.copy_expert(f"""
                COPY {table_name} (article, price)
                FROM STDIN
                WITH (FORMAT CSV);
            """, output)
            conn.commit()

            # Логування часу виконання
            end_time = time.time()
            logging.info(f"Import completed in {end_time - start_time:.2f} seconds.")
            # Flash-повідомлення лише для цієї сторінки
            flash(f"Uploaded {len(data)} rows to table '{table_name}' successfully.", "upload")
            return jsonify({"status": "success",
                            "message": f"Uploaded {len(data)} rows to table '{table_name}' successfully."}), 200

        except Exception as e:
            logging.error(f"Error during POST request: {e}")
            flash("An error occurred during upload.", "error")
            return redirect(request.referrer or url_for('upload_price_list'))
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()


@app.route('/import_status', methods=['GET'])
def get_import_status():
    return jsonify(
        {"status": "success", "message": f"Uploaded {len(data)} rows to table '{table_name}' successfully."}), 200


@app.route('/ping', methods=['GET'])
def ping():
    return "OK", 200


@app.route('/admin/compare_prices', methods=['GET', 'POST'])
def compare_prices():
    if request.method == 'GET':
        try:
            # Отримуємо список таблиць із прайсами
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT table_name FROM price_lists;")
            price_lists = cursor.fetchall()
            conn.close()
            logging.info("Fetched price list tables successfully.")
            return render_template('compare_prices.html', price_lists=price_lists)
        except Exception as e:
            logging.error(f"Error during GET request: {str(e)}", exc_info=True)
            flash("Failed to load price list tables.", "error")
            return redirect(request.referrer or url_for('admin_panel'))

    if request.method == 'POST':
        try:
            form_data = request.form.to_dict()
            logging.info(f"Form data: {form_data}")

            # Якщо запит на експорт
            if 'export_excel' in request.form:
                logging.info("Export to Excel initiated.")
                data = session.get('comparison_results')
                if not data:
                    logging.error("No data to export!")
                    flash("No data to export!", "error")
                    return redirect(request.referrer or url_for('compare_prices'))
                return export_to_excel(
                    data['better_in_first'],
                    data['better_in_second'],
                    data['same_prices']
                )

            # Обробка даних для порівняння
            articles_input = request.form.get('articles', '').strip()
            selected_prices = request.form.getlist('price_tables')

            if not articles_input or not selected_prices:
                flash("Please enter articles and select price tables.", "error")
                return redirect(request.referrer or url_for('compare_prices'))

            # Розбиваємо артикулі
            articles = [line.strip() for line in articles_input.splitlines() if line.strip()]
            logging.info(f"Articles to compare: {articles}")

            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            # Отримуємо ціни з вибраних таблиць
            results = {}
            for table in selected_prices:
                query = f"SELECT article, price FROM {table} WHERE article = ANY(%s);"
                cursor.execute(query, (articles,))
                for row in cursor.fetchall():
                    article = row['article']
                    price = row['price']
                    if article not in results:
                        results[article] = []
                    results[article].append({'price': price, 'table': table})

            conn.close()

            # Порівняння цін
            better_in_first, better_in_second, same_prices = [], [], []
            for article, prices in results.items():
                min_price = min(prices, key=lambda x: x['price'])
                if len([p for p in prices if p['price'] == min_price['price']]) > 1:
                    same_prices.append({
                        'article': article,
                        'price': min_price['price'],
                        'tables': ', '.join(p['table'] for p in prices if p['price'] == min_price['price'])
                    })
                elif min_price['table'] == selected_prices[0]:
                    better_in_first.append({'article': article, **min_price})
                elif min_price['table'] == selected_prices[1]:
                    better_in_second.append({'article': article, **min_price})

            # Зберігаємо результати у сесії
            session['comparison_results'] = {
                'better_in_first': better_in_first,
                'better_in_second': better_in_second,
                'same_prices': same_prices
            }

            logging.info("Comparison completed successfully.")
            return render_template(
                'compare_prices_results.html',
                better_in_first=better_in_first,
                better_in_second=better_in_second,
                same_prices=same_prices
            )

        except Exception as e:
            logging.error(f"Error during POST request: {str(e)}", exc_info=True)
            flash("An error occurred during comparison.", "error")
            return redirect(request.referrer or url_for('compare_prices'))


# Експорт в ексель файлу порівняння цін
def export_to_excel(better_in_first, better_in_second, same_prices):
    try:
        # Створення нового Excel-файлу
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Comparison Results"

        # Додавання даних для першої таблиці
        ws.append(["Better in First Table"])
        ws.append(["Article", "Price"])
        for item in better_in_first:
            ws.append([item['article'], item['price']])
        ws.append([])  # Порожній рядок

        # Додавання даних для другої таблиці
        ws.append(["Better in Second Table"])
        ws.append(["Article", "Price"])
        for item in better_in_second:
            ws.append([item['article'], item['price']])
        ws.append([])  # Порожній рядок

        # Додавання даних для однакових цін
        ws.append(["Same Prices"])
        ws.append(["Article", "Price", "Tables"])
        for item in same_prices:
            ws.append([item['article'], item['price'], item['tables']])

        # Збереження Excel-файлу у тимчасовій директорії
        filename = "comparison_results.xlsx"
        filepath = f"/tmp/{filename}"
        wb.save(filepath)

        # Надсилання файлу користувачеві
        logging.info(f"Exported Excel file saved to: {filepath}")
        return send_file(filepath, as_attachment=True, download_name=filename,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logging.error(f"Error during Excel export: {e}", exc_info=True)
        raise


@app.route('/admin/utilities', methods=['GET'])
def utilities():
    return render_template('utilities.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port)
