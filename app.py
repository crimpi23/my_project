from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify, send_file
import time
import os
import psycopg2
import psycopg2.extras
import logging
import csv
import io
import bcrypt
from functools import wraps
from flask import get_flashed_messages

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
def verify_password(password, stored_hash):
    logging.debug("Verifying password")
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))


# Функція для підключення до бази даних
def get_db_connection():
    return psycopg2.connect(
        dsn=os.environ.get('DATABASE_URL'),
        sslmode="require",
        cursor_factory=psycopg2.extras.DictCursor
    )

# Запит про токен / Перевірка токена / Декоратор для перевірки токена
def requires_token_and_role(required_role):
    """
    Декоратор для перевірки токена і ролі користувача.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(token, *args, **kwargs):
            logging.debug(f"Session token: {session.get('token')}")
            logging.debug(f"Received token: {token}")
            
            if session.get('token') != token:
                flash("Access denied. Token mismatch.", "error")
                return redirect(url_for('index'))

            role_data = validate_token(token)
            logging.debug(f"Role data from token: {role_data}")
            if not role_data or role_data['role'] != required_role:
                flash("Access denied. Invalid role or token.", "error")
                return redirect(url_for('index'))

            session['user_id'] = role_data['user_id']
            session['role'] = role_data['role']
            return func(token, *args, **kwargs)
        return wrapper
    return decorator

#  отримання даних з selection_buffer 
def get_selection_buffer(user_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("""
                SELECT article, price, table_name, quantity
                FROM selection_buffer
                WHERE user_id = %s
                ORDER BY article, price;
            """, (user_id,))
            return cursor.fetchall()


# Головна сторінка за токеном
@app.route('/<token>/')
def token_index(token):
    role = validate_token(token)
    if not role:
        flash("Invalid token.", "error")
        return redirect(url_for('index'))  # Якщо токен недійсний, перенаправляємо на головну

    # Якщо токен валідний, зберігаємо роль і токен у сесії
    session['token'] = token
    session['role'] = role
    return render_template('index.html', role=role)

# Головна сторінка
@app.route('/')
def index():
    token = session.get('token')
    logging.debug(f"Session data in index: {dict(session)}")  # Логування стану сесії

    if not token:
        return render_template('simple_search.html')

    role = session.get('role')
    logging.debug(f"Role in index: {role}")  # Логування ролі користувача

    if role == "admin":
        return redirect(url_for('admin_dashboard', token=token))
    elif role == "user":
        return render_template('index.html', role=role)
    else:
        flash("Invalid token or role.", "error")
        return redirect(url_for('simple_search'))



# Пошук для користувачів без токену
@app.route('/simple_search', methods=['GET', 'POST'])
def simple_search():
    if request.method == 'POST':
        article = request.form.get('article', '').strip()
        if not article:
            # Якщо поле порожнє, виводимо повідомлення
            flash("Please enter an article for search.", "error")
            return redirect(url_for('simple_search'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Отримання списку таблиць з price_lists
            cursor.execute("SELECT table_name FROM price_lists")
            tables = [row['table_name'] for row in cursor.fetchall()]

            results = []
            # Пошук у кожній таблиці
            for table in tables:
                query = f"""
                    SELECT article, price, '{table}' AS table_name
                    FROM {table}
                    WHERE article = %s
                """
                cursor.execute(query, (article,))
                results.extend(cursor.fetchall())

            # Логування результатів
            if results:
                logging.debug(f"Search results for article '{article}': {results}")
            else:
                logging.debug(f"No results found for article '{article}'.")

        except Exception as e:
            logging.error(f"Error in simple_search: {e}", exc_info=True)
            flash("An error occurred during the search. Please try again later.", "error")
            results = []

        finally:
            if 'conn' in locals() and conn:
                conn.close()

        # Відображення результатів
        return render_template('simple_search_results.html', results=results)

    # Простий рендер сторінки пошуку
    return render_template('simple_search.html')





# Доступ до адмін-панелі:
@app.route('/<token>/admin', methods=['GET', 'POST'])
def admin_panel(token):
    try:
        logging.debug(f"Token received in admin_panel: {token}")

        role_data = validate_token(token)
        logging.debug(f"Role data after validation: {role_data}")  # Логування результату перевірки токена

        if not role_data or role_data['role'] != 'admin':
            logging.warning(f"Access denied for token: {token}, Role data: {role_data}")
            flash("Access denied. Admin rights are required.", "error")
            return redirect(url_for('simple_search'))

        session['token'] = token
        session['user_id'] = role_data['user_id']
        session['role'] = role_data['role']  # Збереження ролі в сесії
        logging.debug(f"Session after saving role: {dict(session)}")  # Логування стану сесії

        if request.method == 'POST':
            password = request.form.get('password')
            logging.debug(f"Password entered: {'******' if password else 'None'}")  # Логування введеного пароля

            if not password:
                flash("Password is required.", "error")
                return redirect(url_for('admin_panel', token=token))

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT password_hash 
                FROM users
                WHERE id = %s
            """, (role_data['user_id'],))
            admin_password_hash = cursor.fetchone()
            logging.debug(f"Fetched admin password hash: {admin_password_hash}")  # Логування хешу пароля

            if not admin_password_hash or not verify_password(password, admin_password_hash[0]):
                logging.warning("Invalid admin password attempt.")
                flash("Invalid password.", "error")
                return redirect(url_for('admin_panel', token=token))

            session['admin_authenticated'] = True
            logging.info(f"Admin authenticated for token: {token}")
            return redirect(f'/{token}/admin/dashboard')

        return render_template('admin_login.html', token=token)

    except Exception as e:
        logging.error(f"Error in admin_panel: {e}", exc_info=True)
        flash("An error occurred while accessing the admin panel.", "error")
        return redirect(url_for('simple_search'))

    finally:
        if 'conn' in locals() and conn:
            conn.close()




# Це треба потім описати, теж щось про адмінку
@app.route('/<token>/admin/dashboard')
@requires_token_and_role('admin')
def admin_dashboard(token):
    try:
        logging.debug(f"Session in admin_dashboard: {dict(session)}")  # Логування стану сесії

        if not session.get('admin_authenticated') or session.get('token') != token:
            logging.warning("Access denied. Admin not authenticated or token mismatch.")
            flash("Access denied. Please log in as an admin.", "error")
            return redirect(url_for('admin_panel', token=token))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT u.id, u.username, r.name AS role_name
            FROM users u
            JOIN user_roles ur ON u.id = ur.user_id
            JOIN roles r ON ur.role_id = r.id
        """)
        users = cursor.fetchall()
        logging.debug(f"Fetched users and roles for dashboard: {users}")  # Логування даних користувачів

        return render_template('admin_dashboard.html', users=users, token=token)
    except Exception as e:
        logging.error(f"Error in admin_dashboard: {e}", exc_info=True)
        flash("An error occurred while loading the dashboard.", "error")
        return redirect(url_for('admin_panel', token=token))
    finally:
        if 'conn' in locals() and conn:
            conn.close()





# Функція для перевірки токена
def validate_token(token):
    logging.debug(f"Validating token: {token}")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id AS user_id, r.name AS role
            FROM tokens t
            JOIN users u ON t.user_id = u.id
            JOIN user_roles ur ON ur.user_id = u.id
            JOIN roles r ON ur.role_id = r.id
            WHERE t.token = %s
        """, (token,))
        result = cursor.fetchone()

        if result:
            session['user_id'] = result['user_id']  # Збереження user_id в сесію
            logging.debug(f"User ID stored in session: {result['user_id']}")  # Логування

        conn.close()
        return result if result else None
    except Exception as e:
        logging.error(f"Error validating token: {e}")
        return None



# Створення користувача в адмін панелі:
@app.route('/<token>/admin/create_user', methods=['GET', 'POST'])
@requires_token_and_role('admin')
def create_user(token):
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')  # Отримання email
        role_id = request.form.get('role_id')

        logging.debug(f"Data received in create_user: username={username}, email={email}, role_id={role_id}")

        if not username or not password or not email or not role_id:
            flash("All fields are required.", "error")
            return redirect(url_for('create_user', token=token))

        hashed_password = hash_password(password)
        user_token = generate_token()

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Додавання нового користувача
            cursor.execute("""
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (username, email, hashed_password))
            user_id = cursor.fetchone()['id']

            # Призначення ролі
            cursor.execute("""
                INSERT INTO user_roles (user_id, role_id, assigned_at)
                VALUES (%s, %s, NOW())
            """, (user_id, role_id))

            # Додавання токена
            cursor.execute("""
                INSERT INTO tokens (user_id, token)
                VALUES (%s, %s)
            """, (user_id, user_token))

            conn.commit()
            flash(f"User '{username}' created successfully! Token: {user_token}", "success")
        except Exception as e:
            conn.rollback()
            logging.error(f"Error creating user: {e}", exc_info=True)
            flash("Error creating user. Please check logs.", "error")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        return redirect(url_for('create_user', token=token))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM roles")
    roles = cursor.fetchall()
    conn.close()

    return render_template('create_user.html', roles=roles, token=token)

@app.route('/process_selection', methods=['POST'])
@requires_token_and_role('user')
def process_selection():
    try:
        selected_prices = {}
        for key, value in request.form.items():
            if key.startswith('selected_price_'):
                article = key.replace('selected_price_', '')
                table_name, price = value.split(':')
                selected_prices[article] = {'table_name': table_name, 'price': float(price)}

        user_id = session.get('user_id')
        if not user_id:
            flash("User is not authenticated.", "error")
            return redirect(url_for('index'))

        # Очищення старих записів і додавання нових
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM selection_buffer WHERE user_id = %s", (user_id,))

                for article, data in selected_prices.items():
                    cursor.execute("""
                        INSERT INTO selection_buffer (user_id, article, table_name, price, quantity, added_at)
                        VALUES (%s, %s, %s, %s, 1, NOW());
                    """, (user_id, article, data['table_name'], data['price']))

        flash("Ваш вибір успішно збережено!", "success")
    except Exception as e:
        logging.error(f"Error processing selection: {str(e)}")
        flash("Сталася помилка при обробці вибору. Спробуйте ще раз.", "error")

    return redirect(url_for('search_results'))


@app.route('/search_results', methods=['GET', 'POST'])
@requires_token_and_role('user')
def search_results():
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to view search results.", "error")
        return redirect(url_for('index'))

    results = get_selection_buffer(user_id)

    # Групуємо результати за артикулом
    grouped_results = {}
    for row in results:
        article = row['article']
        if article not in grouped_results:
            grouped_results[article] = []
        grouped_results[article].append({
            'price': row['price'],
            'table_name': row['table_name'],
            'quantity': row['quantity'],
        })

    return render_template('search_results.html', grouped_results=grouped_results)



# Маршрут для пошуку артикулів
@app.route('/<token>/search', methods=['POST'])
@requires_token_and_role('user')
def search_articles(token):  
    """
    Маршрут для пошуку артикулів.
    """
    conn = None
    cursor = None
    try:
        logging.info("Processing search request...")
        articles = []
        quantities = {}
        auto_set_quantities = []

        articles_input = request.form.get('articles')
        logging.debug(f"Received articles input: {articles_input}")

        if not articles_input:
            flash("Please enter at least one article.", "error")
            return redirect(url_for('index'))

        # Обробка вхідних даних
        for line in articles_input.splitlines():
            parts = line.strip().split()
            if not parts:
                continue  # Пропустити порожні рядки
            if len(parts) == 1:
                article = parts[0].strip().upper()
                if article in quantities:
                    quantities[article] += 1
                else:
                    articles.append(article)
                    quantities[article] = 1  # За замовчуванням додаємо 1
                    auto_set_quantities.append(article)
            elif len(parts) == 2 and parts[1].isdigit():
                article, quantity = parts[0].strip().upper(), int(parts[1])
                if article in quantities:
                    quantities[article] += quantity
                else:
                    articles.append(article)
                    quantities[article] = quantity

        logging.debug(f"Processed articles: {articles}")
        logging.debug(f"Quantities: {quantities}")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримання таблиць з прайс-листами
        cursor.execute("SELECT table_name FROM price_lists")
        tables = cursor.fetchall()
        logging.debug(f"Fetched price list tables: {tables}")

        results = []
        for table in tables:
            table_name = table['table_name']
            logging.debug(f"Querying table: {table_name}")
            query = f"""
                SELECT article, price, %s AS table_name
                FROM {table_name}
                WHERE article = ANY(%s)
            """
            cursor.execute(query, (table_name, articles))
            results.extend(cursor.fetchall())
            logging.debug(f"Results from table {table_name}: {cursor.rowcount}")

        grouped_results = {}
        for result in results:
            article = result['article']
            grouped_results.setdefault(article, []).append({
                'price': result['price'],
                'table_name': result['table_name'],
                'quantity': quantities.get(article, 1)  # Додаємо кількість до результатів
            })

        missing_articles = [article for article in articles if article not in grouped_results]
        logging.info(f"Missing articles: {missing_articles}")

        # Збереження результатів у сесії
        session['grouped_results'] = grouped_results
        session['quantities'] = quantities
        session['missing_articles'] = missing_articles

        logging.info("Search results successfully processed.")

        if not grouped_results:
            flash("No results found for your search.", "info")
            return render_template('search_results.html', grouped_results={}, quantities=quantities, missing_articles=missing_articles)

        flash("Search completed successfully!", "success")
        return render_template('search_results.html', grouped_results=grouped_results, quantities=quantities, missing_articles=missing_articles)

    except Exception as e:
        logging.error(f"Error in search_articles: {str(e)}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logging.info("Database connection closed.")







# очищення результату пошуку
@app.route('/<token>/clear_search', methods=['POST'])
@requires_token_and_role('user')
def clear_search(token):
    try:
        logging.debug("Clearing search data from session.")
        session.pop('grouped_results', None)
        session.pop('quantities', None)
        session.pop('missing_articles', None)
        flash("Search data cleared successfully.", "success")
    except Exception as e:
        logging.error(f"Error clearing search data: {str(e)}", exc_info=True)
        flash("Could not clear search data. Please try again.", "error")
    
    # Перенаправлення на головну сторінку
    return redirect(url_for('token_index', token=token))



# Сторінка кошика
@app.route('/<token>/cart', methods=['GET', 'POST'])
@requires_token_and_role('user')
def cart(token):
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash("You need to log in to view your cart.", "error")
            return redirect(url_for('index'))

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cursor.execute("""
            SELECT 
                c.product_id, 
                p.article, 
                p.price, 
                c.quantity, 
                (p.price * c.quantity) AS total_price, 
                c.added_at
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
            ORDER BY c.added_at
        """, (user_id,))
        cart_items = cursor.fetchall()

        # Логування вмісту кошика
        logging.debug(f"Cart items for user_id={user_id}: {cart_items}")

        # Розрахунок загальної суми
        total_price = sum(item['total_price'] for item in cart_items)

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



# Додавання в кошик користувачем
@app.route('/<token>/add_to_cart', methods=['POST'])
@requires_token_and_role('user')
def add_to_cart(token):
    """
    Додає товар до кошика користувача.
    """
    conn = None
    cursor = None
    try:
        # Отримання даних з форми
        article = request.form.get('article')
        price = float(request.form.get('price'))
        quantity = int(request.form.get('quantity'))  # Перевіряємо кількість товару
        table_name = request.form.get('table_name')
        user_id = session.get('user_id')  # Отримання ID користувача із сесії

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            return redirect(url_for('index'))

        logging.debug(f"Adding to cart: Article={article}, Price={price}, Quantity={quantity}, Table={table_name}, User={user_id}")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Перевірка наявності товару у таблиці `products`
        cursor.execute("""
            SELECT id FROM products
            WHERE article = %s AND table_name = %s
        """, (article, table_name))
        product = cursor.fetchone()

        if not product:
            # Додавання нового продукту в таблицю `products`
            cursor.execute("""
                INSERT INTO products (article, table_name, price)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (article, table_name, price))
            product_id = cursor.fetchone()[0]
            logging.info(f"New product added to 'products': ID={product_id}, Article={article}, Table={table_name}, Price={price}")
        else:
            product_id = product['id']
            logging.debug(f"Product already exists: ID={product_id}, Article={article}")

        # Перевірка, чи товар вже є в кошику
        cursor.execute("""
            SELECT id FROM cart
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        existing_cart_item = cursor.fetchone()

        if existing_cart_item:
            # Оновлення кількості товару в кошику
            cursor.execute("""
                UPDATE cart
                SET quantity = quantity + %s
                WHERE id = %s
            """, (quantity, existing_cart_item['id']))
            logging.info(f"Cart updated: Product ID={product_id}, Quantity Added={quantity}, User ID={user_id}")
        else:
            # Додавання нового товару в кошик
            cursor.execute("""
                INSERT INTO cart (user_id, product_id, quantity, added_at)
                VALUES (%s, %s, %s, NOW())
            """, (user_id, product_id, quantity))
            logging.info(f"Product added to cart: Product ID={product_id}, Quantity={quantity}, User ID={user_id}")

        conn.commit()
        flash("Product added to cart!", "success")
    except Exception as e:
        logging.error(f"Error in add_to_cart: {e}", exc_info=True)
        flash("Error adding product to cart.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            logging.debug("Database connection closed after adding to cart.")

    # Перенаправлення на сторінку результатів пошуку
    return render_template(
        'search_results.html',
        grouped_results=session.get('grouped_results', {}),
        quantities=session.get('quantities', {}),
        missing_articles=session.get('missing_articles', []),
    )



# Видалення товару з кошика
@app.route('/<token>/remove_from_cart', methods=['POST'])
def remove_from_cart(token):
    conn = None
    cursor = None
    try:
        product_id = request.form.get('product_id')
        user_id = session.get('user_id')  # Отримати ID поточного користувача з сесії

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            return redirect(url_for('index'))

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
@app.route('/<token>/update_cart', methods=['POST'])
@requires_token_and_role('user')
def update_cart(token):
    """
    Оновлює кількість товарів у кошику.
    """
    conn = None
    cursor = None
    try:
        # Отримуємо дані з форми
        product_id = request.form.get('product_id')
        quantity = request.form.get('quantity')
        user_id = session.get('user_id')  # Отримання ID користувача із сесії

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            return redirect(url_for('index'))

        if not product_id or not quantity:
            flash("Invalid input: product_id or quantity missing.", "error")
            logging.error("Missing product_id or quantity in update_cart form.")
            return redirect(url_for('cart', token=token))

        product_id = int(product_id)
        quantity = int(quantity)

        if quantity < 1:
            flash("Quantity must be at least 1.", "error")
            logging.error(f"Invalid quantity: {quantity}")
            return redirect(url_for('cart', token=token))

        logging.debug(f"Updating cart: Product ID={product_id}, Quantity={quantity}, User={user_id}")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Оновлення кількості у кошику
        cursor.execute("""
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND product_id = %s
        """, (quantity, user_id, product_id))

        conn.commit()
        flash("Cart updated successfully!", "success")
    except Exception as e:
        logging.error(f"Error updating cart: {e}", exc_info=True)
        flash("Error updating cart.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            logging.debug("Database connection closed after updating cart.")

    # Повернення до кошика
    return redirect(url_for('cart', token=token))





# Очищення кошика користувача
@app.route('/<token>/clear_cart', methods=['POST'])
@requires_token_and_role('user')
def clear_cart(token):
    try:
        user_id = session.get('user_id')

        if not user_id:
            flash("User is not authenticated.", "error")
            return redirect(url_for('index'))

        conn = get_db_connection()
        cursor = conn.cursor()

        # Видалення всіх елементів кошика для поточного користувача
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()

        logging.info(f"Cart cleared for user_id={user_id}.")
        flash("Cart cleared successfully.", "success")
    except Exception as e:
        logging.error(f"Error clearing cart for user_id={user_id}: {e}", exc_info=True)
        flash("Error clearing cart.", "error")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return redirect(url_for('cart', token=token))  # Перенаправлення на сторінку кошика






# Оформлення замовлення
@app.route('/<token>/place_order', methods=['POST'])
@requires_token_and_role('user')
def place_order(token):
    try:
        user_id = session.get('user_id')  # Отримати ID поточного користувача з сесії

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            return redirect(url_for('index'))

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

        # Вставка замовлення в таблицю orders зі статусом "Pending"
        cursor.execute("""
            INSERT INTO orders (user_id, total_price, order_date, status)
            VALUES (%s, %s, NOW(), %s)
            RETURNING id
        """, (user_id, total_price, "Pending"))
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
        if conn:
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



# Замовлення користувача
@app.route('/<token>/orders', methods=['GET'])
@requires_token_and_role('user')
def orders(token):
    user_id = session.get('user_id')
    if not user_id:
        flash("User is not authenticated.", "error")
        return redirect(url_for('index'))

    # Отримуємо фільтри з запиту
    article_filter = request.args.get('article', '')
    status_filter = request.args.get('status', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    # Логування отриманих фільтрів
    logging.debug(f"Received filters: Article: {article_filter}, Status: {status_filter}, Start Date: {start_date}, End Date: {end_date}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Початковий запит до таблиці orders
        query = """
        SELECT * FROM orders
        WHERE user_id = %s
        ORDER BY order_date DESC
        """
        params = [user_id]

        # Якщо фільтр по артикулу
        if article_filter:
            query += " AND EXISTS (SELECT 1 FROM order_items WHERE order_id = orders.id AND article LIKE %s)"
            params.append(f"%{article_filter}%")

        # Якщо фільтр по статусу
        if status_filter:
            query += " AND status = %s"
            params.append(status_filter)

        # Якщо фільтр по даті початку
        if start_date:
            query += " AND order_date >= %s"
            params.append(start_date)

        # Якщо фільтр по даті кінця
        if end_date:
            query += " AND order_date <= %s"
            params.append(end_date)

        # Логування сформованого запиту
        logging.debug(f"Executing query: {query} with params: {params}")

        cursor.execute(query, params)
        orders = cursor.fetchall()

        logging.debug(f"Orders retrieved for user_id={user_id} with filters: {article_filter}, {status_filter}, {start_date}, {end_date}")
        conn.commit()
        cursor.close()
        conn.close()

        return render_template('orders.html', orders=orders)
    except Exception as e:
        logging.error(f"Error fetching orders: {e}", exc_info=True)
        flash("Error fetching orders.", "error")
        return redirect(url_for('orders', token=token))




# Окреме замовлення пористувача по id
@app.route('/<token>/order_details/<int:order_id>')
@requires_token_and_role('user') 
def order_details(token, order_id):
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

@app.route('/<token>/admin/orders/<int:order_id>/update_status', methods=['POST'])
@requires_token_and_role('admin')
def update_order_item_status(token, order_id):
    """
    Update the status of specific order items.
    """
    try:
        data = request.json  # Очікуємо JSON-дані
        if not data:
            logging.warning("No JSON data received.")
            return jsonify({"error": "Invalid JSON data."}), 400
        
        user_id = session.get('user_id')  # ID адміністратора
        conn = get_db_connection()
        cursor = conn.cursor()

        logging.info(f"Received data for order {order_id}: {data}")

        # Перевіряємо наявність елементів
        if not data.get('items'):
            logging.warning("No items found in request data.")
            return jsonify({"error": "No items provided."}), 400

        for item in data.get('items', []):
            detail_id = item.get('id')
            new_status = item.get('status')
            comment = item.get('comment', None)

            # Перевіряємо обов'язкові поля
            if not detail_id or not new_status:
                logging.warning(f"Missing required fields for item: {item}")
                continue

            # Отримуємо поточний статус
            cursor.execute("SELECT status FROM order_details WHERE id = %s;", (detail_id,))
            current_status = cursor.fetchone()

            if current_status:
                current_status = current_status[0]
                logging.info(f"Updating item {detail_id}: {current_status} -> {new_status}")

                # Оновлюємо статус елемента
                cursor.execute("""
                    UPDATE order_details
                    SET status = %s, comment = %s
                    WHERE id = %s;
                """, (new_status, comment, detail_id))

                # Логування змін
                cursor.execute("""
                    INSERT INTO order_changes (order_id, order_detail_id, field_changed, old_value, new_value, comment, changed_by)
                    VALUES (%s, %s, 'status', %s, %s, %s, %s);
                """, (order_id, detail_id, current_status, new_status, comment, user_id))

        conn.commit()
        logging.info(f"Item statuses for order {order_id} updated successfully.")

        # Оновлення статусу замовлення
        cursor.execute("""
            SELECT COUNT(*) FILTER (WHERE status = 'new') AS new_count,
                   COUNT(*) FILTER (WHERE status = 'accepted') AS accepted_count,
                   COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count
            FROM order_details
            WHERE order_id = %s;
        """, (order_id,))
        counts = cursor.fetchone()

        if counts:
            if counts[0] == 0 and counts[1] == 0:
                new_order_status = 'cancelled'
            elif counts[1] > 0:
                new_order_status = 'accepted'
            else:
                new_order_status = 'new'

            cursor.execute("UPDATE orders SET status = %s WHERE id = %s;", (new_order_status, order_id))
            conn.commit()
            logging.info(f"Order {order_id} status updated to {new_order_status}.")

        flash("Order and item statuses updated successfully.", "success")
    except Exception as e:
        logging.error(f"Error in updating order items for order {order_id}: {e}")
        return jsonify({"error": "An error occurred while processing the request."}), 500
    finally:
        if conn:
            conn.close()
            logging.info(f"Database connection closed for order {order_id}.")

    return jsonify({"message": "Statuses updated successfully."})




@app.route('/<token>/admin/orders/<int:order_id>', methods=['GET'])
@requires_token_and_role('admin')
def admin_order_details(token, order_id):
    """
    Display detailed view of a specific order for admin.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Get order details
        cursor.execute("SELECT id, user_id, order_date, total_price FROM orders WHERE id = %s;", (order_id,))
        order = cursor.fetchone()

        if not order:
            flash("Order not found.", "error")
            return redirect(url_for('admin_orders', token=token))

        # Map order details to a dictionary
        order_data = {
            'id': order[0],
            'user_id': order[1],
            'order_date': order[2],
            'total_price': order[3],
        }

        # Get order items
        cursor.execute("""
            SELECT id, product_id, price, quantity, total_price, status, comment
            FROM order_details
            WHERE order_id = %s;
        """, (order_id,))
        order_items = cursor.fetchall()

        # Map order items to a list of dictionaries
        order_items_data = [
            {
                'id': item[0],
                'product_id': item[1],
                'price': item[2],
                'quantity': item[3],
                'total_price': item[4],
                'status': item[5],
                'comment': item[6],
            }
            for item in order_items
        ]

        return render_template('admin_order_details.html', order=order_data, order_items=order_items_data, token=token)
    except Exception as e:
        logging.error(f"Error fetching order details: {e}")
        flash("Failed to load order details.", "error")
        return redirect(url_for('admin_orders', token=token))
    finally:
        conn.close()


@app.route('/<token>/admin/orders', methods=['GET'])
@requires_token_and_role('admin')
def admin_orders(token):
    """
    Display all orders for the admin.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Fetch all orders
        cursor.execute("SELECT * FROM orders ORDER BY order_date DESC;")
        orders = cursor.fetchall()

        return render_template('admin_orders.html', orders=orders, token=token)
    except Exception as e:
        logging.error(f"Error fetching orders: {e}")
        flash("Failed to load orders.", "error")
        return redirect(url_for('admin_dashboard', token=token))
    finally:
        conn.close()


# Ролі користувачеві    
@app.route('/<token>/admin/assign_roles', methods=['GET', 'POST'])
@requires_token_and_role('admin')  # Вкажіть 'admin' або іншу роль
def assign_roles(token):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Отримання користувачів і ролей
    cursor.execute("""
        SELECT users.id AS user_id, users.username, roles.id AS role_id, roles.name AS role_name
        FROM user_roles
        JOIN users ON user_roles.user_id = users.id
        JOIN roles ON user_roles.role_id = roles.id
        ORDER BY users.username;
    """)
    user_roles = cursor.fetchall()

    cursor.execute("SELECT id, username FROM users;")
    users = cursor.fetchall()

    cursor.execute("SELECT id, name FROM roles;")
    roles = cursor.fetchall()

    if request.method == 'POST':
        action = request.form['action']
        user_id = request.form['user_id']
        role_id = request.form['role_id']

        try:
            if action == 'assign':
                cursor.execute("""
                    SELECT * FROM user_roles
                    WHERE user_id = %s AND role_id = %s;
                """, (user_id, role_id))
                if cursor.fetchone():
                    flash("Role already assigned.", "warning")
                else:
                    cursor.execute("""
                        INSERT INTO user_roles (user_id, role_id)
                        VALUES (%s, %s);
                    """, (user_id, role_id))
                    conn.commit()
                    flash("Role assigned successfully.", "success")
            elif action == 'remove':
                cursor.execute("""
                    DELETE FROM user_roles
                    WHERE user_id = %s AND role_id = %s;
                """, (user_id, role_id))
                conn.commit()
                flash("Role removed successfully.", "success")
        except Exception as e:
            conn.rollback()
            logging.error(f"Error assigning/removing role: {e}", exc_info=True)
            flash("Error assigning/removing role.", "error")

        # Перенаправляємо на ту ж сторінку
        return redirect(url_for('assign_roles', token=token))

    conn.close()
    return render_template('assign_roles.html', user_roles=user_roles, users=users, roles=roles, token=token)




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
@app.route('/<token>/admin/upload_price_list', methods=['GET', 'POST'])
@requires_token_and_role('admin')
def upload_price_list(token):
    """
    Обробляє завантаження прайс-листу.
    - GET: Повертає сторінку завантаження.
    - POST: Обробляє завантаження файлу та записує дані в базу.
    """
    if request.method == 'GET':
        try:
            logging.info(f"Accessing upload page for token: {token}")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM price_lists;")
            price_lists = cursor.fetchall()
            conn.close()
            logging.info(f"Fetched price lists: {price_lists}")
            return render_template('upload_price_list.html', price_lists=price_lists, token=token)
        except Exception as e:
            logging.error(f"Error during GET request: {e}")
            flash("Error loading the upload page.", "error")
            return redirect(url_for('admin_dashboard', token=token))

    if request.method == 'POST':
        try:
            logging.info(f"Starting file upload for token: {token}")
            start_time = time.time()

            # Отримання параметрів форми
            table_name = request.form['table_name']
            new_table_name = request.form.get('new_table_name', '').strip()
            file = request.files.get('file')

            # Логування вхідних даних
            logging.debug(f"Received table_name: {table_name}, new_table_name: {new_table_name}")

            if not file or file.filename == '':
                flash("No file uploaded or selected.", "error")
                logging.warning("No file uploaded or selected.")
                return redirect(url_for('upload_price_list', token=token))

            # Читання файлу
            file_content = file.read().decode('utf-8', errors='ignore')
            delimiter = detect_delimiter(file_content)
            logging.debug(f"Detected delimiter: {delimiter}")
            reader = csv.reader(io.StringIO(file_content), delimiter=delimiter)

            # Обробка даних з файлу
            data = []
            header_skipped = False
            for row in reader:
                if len(row) < 2:
                    logging.warning(f"Skipping invalid row: {row}")
                    continue
                if not header_skipped and not row[1].replace(',', '').replace('.', '').isdigit():
                    header_skipped = True
                    logging.info(f"Skipped header row: {row}")
                    continue
                try:
                    article = row[0].strip().replace(" ", "").upper()
                    price = float(row[1].replace(",", ".").strip())
                    data.append((article, price))
                except ValueError:
                    logging.warning(f"Skipping row with invalid price: {row}")
                    continue

            logging.info(f"Parsed {len(data)} rows from file. Sample: {data[:5]}")

            # Підключення до бази даних
            conn = get_db_connection()
            cursor = conn.cursor()

            # Логіка для створення нової таблиці
            if table_name == 'new':
                if not new_table_name:
                    flash("New table name is required.", "error")
                    logging.error("New table name was not provided.")
                    return redirect(url_for('upload_price_list', token=token))

                table_name = new_table_name.strip().replace(" ", "_").lower()
                if not re.match(r'^[a-z_][a-z0-9_]*$', table_name):
                    logging.warning(f"Invalid table name: {table_name}")
                    flash("Invalid table name. Only lowercase letters, numbers, and underscores are allowed.", "error")
                    return redirect(url_for('upload_price_list', token=token))

                try:
                    cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            article TEXT PRIMARY KEY,
                            price NUMERIC
                        );
                    """)
                    cursor.execute("INSERT INTO price_lists (table_name, created_at) VALUES (%s, NOW());", (table_name,))
                    conn.commit()
                    logging.info(f"Created new table: {table_name}")
                except Exception as e:
                    logging.error(f"Error creating new table {table_name}: {e}")
                    flash("Error creating new table. Please check the table name and try again.", "error")
                    return redirect(url_for('upload_price_list', token=token))

            # Перевірка існування таблиці
            try:
                cursor.execute(f"SELECT 1 FROM information_schema.tables WHERE table_name = %s;", (table_name,))
                if cursor.fetchone() is None:
                    flash(f"Table '{table_name}' does not exist. Please try again.", "error")
                    logging.error(f"Table '{table_name}' does not exist.")
                    return redirect(url_for('upload_price_list', token=token))
            except Exception as e:
                logging.error(f"Error checking table existence: {e}")
                flash("An error occurred while verifying the table. Please try again.", "error")
                return redirect(url_for('upload_price_list', token=token))

            # Очищення таблиці
            cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY;")
            conn.commit()
            logging.info(f"Truncated table: {table_name}")

            # Завантаження даних у таблицю
            output = io.StringIO()
            for row in data:
                output.write(f"{row[0]},{row[1]}\n")
            output.seek(0)
            cursor.copy_expert(f"COPY {table_name} (article, price) FROM STDIN WITH (FORMAT CSV);", output)
            conn.commit()

            end_time = time.time()
            flash(f"Uploaded {len(data)} rows to table '{table_name}' successfully.", "success")
            logging.info(f"Uploaded {len(data)} rows to table '{table_name}' in {end_time - start_time:.2f} seconds.")
            return redirect(url_for('upload_price_list', token=token))

        except Exception as e:
            logging.error(f"Error during POST request: {e}")
            flash("An error occurred during upload.", "error")
            return redirect(url_for('upload_price_list', token=token))
        finally:
            if 'conn' in locals() and conn:
                conn.close()
                logging.info("Database connection closed.")





# 
@app.route('/import_status', methods=['GET'])
def get_import_status():
    logging.info("get_import_status function called.")
    return jsonify(
        {"status": "success", "message": f"Uploaded {len(data)} rows to table '{table_name}' successfully."}), 200




@app.route('/<token>/admin/compare_prices', methods=['GET', 'POST'])
@requires_token_and_role('admin')
def compare_prices(token):
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


@app.route('/<token>/admin/utilities')
@requires_token_and_role('admin')
def utilities(token):
    return render_template('utilities.html', token=token)


@app.route('/ping', methods=['GET'])
def ping():
    logging.info("ping function called.")  
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port)
