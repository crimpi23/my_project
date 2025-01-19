from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify, send_file, get_flashed_messages
from decimal import Decimal
import time
import os
import psycopg2
import psycopg2.extras
import logging
import csv
import io
import bcrypt
import pandas as pd
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
def verify_password(password, stored_hash):
    logging.debug("Verifying password")
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))

def get_all_price_list_tables():
    """
    Отримує список усіх таблиць із таблиці price_lists.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM price_lists;")
            tables = [row[0] for row in cursor.fetchall()]
            logging.debug(f"Fetched tables from price_lists: {tables}")
            return tables
    except Exception as e:
        logging.error(f"Error fetching price list tables: {e}", exc_info=True)
        return []


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

# функція націнки для користувачів
def calculate_price(base_price, markup_percentage):
    # Розрахунок кінцевої ціни з урахуванням націнки
    markup_multiplier = Decimal(1) + (Decimal(markup_percentage) / Decimal(100))
    return round(base_price * markup_multiplier, 2)



def get_markup_by_role(role_name):
    """
    Отримання націнки за роллю.
    """
    # Приклад: націнки для ролей
    role_markup_mapping = {
        "admin_user": 0,   # без націнки
        "manager_user": 35,
        "user_29": 29,
        "user_25": 25,
    }
    return role_markup_mapping.get(role_name, 35)  # стандартна націнка 35%


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



# Маршрут для пошуку артикулів
@app.route('/<token>/search', methods=['GET', 'POST'])
@requires_token_and_role('user')
def search_articles(token):
    logging.info(f"Started search_articles with token: {token}")
    conn = None
    cursor = None
    try:
        articles = []
        quantities = {}
        comments = {}

        articles_input = request.form.get('articles')
        logging.debug(f"Received articles input: {articles_input}")

        if not articles_input:
            flash("Please enter at least one article.", "error")
            return redirect(url_for('index'))

        # Process the input lines for articles
        for line in articles_input.splitlines():
            parts = line.strip().split('\t')
            if len(parts) == 0:
                continue

            article = parts[0].strip().upper()

            if len(parts) > 1 and parts[1].isdigit():
                quantity = int(parts[1])
            else:
                quantity = 1  # Default quantity

            if len(parts) > 2:
                comment = parts[2].strip()
            else:
                comment = None  # No comment provided

            quantities[article] = quantities.get(article, 0) + quantity
            comments[article] = comment  # Store comment for the article
            articles.append(article)

        logging.debug(f"Processed articles: {articles}")
        logging.debug(f"Quantities: {quantities}")
        logging.debug(f"Comments: {comments}")

        conn = get_db_connection()
        cursor = conn.cursor()
        logging.info("Database connection established.")

        # Get the markup percentage for the user
        user_markup = Decimal(get_markup_percentage(session['user_id']))
        if user_markup < 0:
            logging.warning(f"Invalid markup percentage: {user_markup}. Defaulting to 0.")
            user_markup = Decimal(0)
        logging.debug(f"Markup percentage for user_id={session['user_id']}: {user_markup}%")

        # Fetch all tables from price_lists
        cursor.execute("SELECT table_name FROM price_lists")
        tables = [row[0] for row in cursor.fetchall()]
        logging.debug(f"Fetched price list tables: {tables}")

        results = []
        for table_name in tables:
            logging.debug(f"Querying table: {table_name}")
            query = f"""
                SELECT article, price, %s AS table_name
                FROM {table_name}
                WHERE article = ANY(%s)
            """
            cursor.execute(query, (table_name, articles))
            fetched = cursor.fetchall()
            results.extend(fetched)
            logging.debug(f"Results from table {table_name}: {len(fetched)} rows")

        grouped_results = {}
        for result in results:
            article = result['article']
            base_price = Decimal(result['price'])
            final_price = round(base_price * (1 + user_markup / 100), 2)
            grouped_results.setdefault(article, []).append({
                'price': final_price,
                'base_price': base_price,
                'table_name': result['table_name'],
                'quantity': quantities.get(article, 1),
                'comment': comments.get(article)  # Include the comment
            })

        missing_articles = [article for article in articles if article not in grouped_results]
        if missing_articles:
            flash(f"The following articles were not found in any price list: {', '.join(missing_articles)}", "warning")
            logging.info(f"Missing articles for user_id={session['user_id']}: {missing_articles}")
        else:
            logging.info("No missing articles found.")

        logging.debug(f"Grouped results: {grouped_results}")

        session['grouped_results'] = grouped_results
        session['quantities'] = quantities
        session['comments'] = comments  # Store comments in the session
        session['missing_articles'] = missing_articles

        logging.info("Search results successfully processed.")

        if not grouped_results:
            flash("No results found for your search.", "info")
            return render_template('search_results.html', grouped_results={}, quantities=quantities, missing_articles=missing_articles)

        flash("Search completed successfully!", "success")
        return render_template(
            'search_results.html',
            grouped_results=grouped_results,
            quantities=quantities,
            comments=comments, 
            missing_articles=missing_articles,
            token=token
        )


    except Exception as e:
        logging.error(f"Error in search_articles: {str(e)}", exc_info=True)
        flash("An error occurred while processing your search. Please try again.", "error")
        return redirect(url_for('index'))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logging.info("Database connection closed.")



@app.route('/<token>/search_results', methods=['GET'])
@requires_token_and_role('user')
def search_results(token):
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to view search results.", "error")
        return redirect(url_for('index'))

    user_markup = Decimal(get_markup_percentage(user_id))
    logging.debug(f"Markup percentage for user_id={user_id}: {user_markup}%")

    results = get_selection_buffer(user_id)
    grouped_results = {}
    for row in results:
        base_price = Decimal(row['price'])
        final_price = round(base_price * (Decimal(1) + user_markup / Decimal(100)), 2)
        grouped_results.setdefault(row['article'], []).append({
            'price': final_price,
            'table_name': row['table_name'],
            'quantity': row['quantity'],
        })

    return render_template('search_results.html', grouped_results=grouped_results, token=token)




@app.route('/<token>/cart', methods=['GET', 'POST'])
@requires_token_and_role('user')
def cart(token):
    """
    Функція для обробки кошика користувача:
    - Відображає товари у кошику.
    - Відображає відсутні артикули.
    - Дозволяє оновлювати кількість або видаляти товари.
    """
    try:
        # Отримуємо ID користувача з сесії
        user_id = session.get('user_id')
        if not user_id:
            flash("You need to log in to view your cart.", "error")
            logging.warning("Attempt to access cart without user ID.")
            return redirect(url_for('index'))

        logging.debug(f"User ID: {user_id} accessed the cart.")

        # Підключення до бази даних
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Якщо це POST-запит, обробляємо дії з кошиком (видалення, оновлення кількості)
        if request.method == 'POST':
            action = request.form.get('action')
            product_id = request.form.get('product_id')
            logging.debug(f"POST action received: {action}, product_id: {product_id}")
            if action == 'remove' and product_id:
                # Видалення товару з кошика
                cursor.execute(
                    """
                    DELETE FROM cart
                    WHERE user_id = %s AND product_id = %s
                    """,
                    (user_id, product_id)
                )
                conn.commit()
                flash("Item removed from cart.", "success")
                logging.info(f"Product {product_id} removed from cart for user_id {user_id}.")
            elif action == 'update_quantity' and product_id:
                # Оновлення кількості товару
                new_quantity = int(request.form.get('quantity', 1))
                if new_quantity > 0:
                    cursor.execute(
                        """
                        UPDATE cart
                        SET quantity = %s
                        WHERE user_id = %s AND product_id = %s
                        """,
                        (new_quantity, user_id, product_id)
                    )
                    conn.commit()
                    flash("Item quantity updated.", "success")
                    logging.info(f"Product {product_id} quantity updated to {new_quantity} for user_id {user_id}.")
                else:
                    flash("Quantity must be greater than zero.", "error")
                    logging.warning(f"Invalid quantity {new_quantity} provided for product {product_id}.")

        # Отримуємо товари з кошика
        cursor.execute("""
            SELECT 
                c.product_id, 
                p.article, 
                COALESCE(c.base_price, 0) AS base_price,
                COALESCE(c.final_price, 0) AS final_price,
                c.quantity,
                ROUND(COALESCE(c.final_price, 0) * c.quantity, 2) AS total_price
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
            ORDER BY c.added_at
        """, (user_id,))

        cart_items = []
        for row in cursor.fetchall():
            cart_items.append({
                'product_id': row['product_id'],
                'article': row['article'],
                'base_price': float(row['base_price']),
                'final_price': float(row['final_price']),
                'quantity': row['quantity'],
                'total_price': float(row['total_price'])
            })
        logging.debug(f"Cart items fetched: {cart_items}")

        # Отримання відсутніх артикулів із сесії
        missing_articles = session.get('missing_articles', [])
        logging.debug(f"Missing articles from session before processing: {missing_articles}")
        if missing_articles:
            missing_articles = list(set(missing_articles))  # Уникнення повторень
        logging.debug(f"Unique missing articles after processing: {missing_articles}")

        # Підрахунок загальної суми
        total_price = sum(item['total_price'] for item in cart_items)
        logging.debug(f"Total price calculated: {total_price}. Preparing to render cart page.")

        # Логування для рендерингу
        logging.info(f"Rendering cart for user_id={user_id}. Cart items count: {len(cart_items)}, Missing articles count: {len(missing_articles)}")

        return render_template(
            'cart.html',
            cart_items=cart_items,
            total_price=total_price,
            missing_articles=missing_articles,
            token=token
        )

    except Exception as e:
        logging.error(f"Error in cart for user_id={user_id}: {str(e)}", exc_info=True)
        flash("Could not load your cart. Please try again.", "error")
        return redirect(url_for('index'))

    finally:
        # Закриваємо курсор і підключення
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
        logging.debug("Database connection closed.")




# проміжковий єтап після cart
@app.route('/<token>/submit_selection', methods=['POST'])
@requires_token_and_role('user')
def submit_selection(token):
    logging.debug(f"Submit Selection Called with token: {token}")
    app.logger.debug(f"Form data received: {request.form}")

    try:
        user_id = session.get('user_id')
        if not user_id:
            flash("User not authenticated", "error")
            logging.warning("User not authenticated. Redirecting to search.")
            return redirect(url_for('search_articles', token=token))

        # Обробка форми для вибраних товарів
        selected_articles = []
        for key, value in request.form.items():
            if key.startswith('selected_'):
                article = key.split('_')[1]
                price, table_name = value.split('|')
                quantity_key = f"quantity_{article}"
                comment_key = f"comment_{article}"
                quantity = int(request.form.get(quantity_key, 1))
                comment = request.form.get(comment_key, "").strip()
                selected_articles.append((article, Decimal(price), table_name, quantity, comment))
                logging.debug(f"Processed article: {article}, price: {price}, table: {table_name}, quantity: {quantity}, comment: {comment}")

        if not selected_articles:
            flash("No articles selected.", "error")
            logging.info("No articles selected in the form. Redirecting to search.")
            return redirect(url_for('search_articles', token=token))

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            for article, price, table_name, quantity, comment in selected_articles:
                # Перевірка, чи існує товар у `products`
                cursor.execute("""
                    SELECT id FROM products WHERE article = %s AND table_name = %s
                """, (article, table_name))
                product = cursor.fetchone()

                if not product:
                    # Додавання нового товару до `products`
                    cursor.execute("""
                        INSERT INTO products (article, table_name, price, created_at)
                        VALUES (%s, %s, %s, NOW())
                        RETURNING id
                    """, (article, table_name, price))
                    product = cursor.fetchone()
                    logging.info(f"Added new product to products: {article}, table: {table_name}, price: {price}")

                product_id = product['id']

                # Додавання товару в кошик
                cursor.execute("""
                    INSERT INTO cart (user_id, product_id, quantity, base_price, final_price, comment, added_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, product_id) DO UPDATE SET
                    quantity = cart.quantity + EXCLUDED.quantity,
                    final_price = EXCLUDED.final_price,
                    comment = EXCLUDED.comment
                """, (user_id, product_id, quantity, price, price, comment))
                logging.debug(f"Added/updated article {article} in cart for user_id={user_id}.")

            conn.commit()
            logging.info(f"Cart updated successfully for user_id={user_id}.")

        flash("Selection successfully submitted!", "success")
        return redirect(url_for('cart', token=token))

    except Exception as e:
        logging.error(f"Error in submit_selection: {e}", exc_info=True)
        flash("An error occurred during submission. Please try again.", "error")
        return redirect(url_for('search_articles', token=token))





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
@requires_token_and_role('user')
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
        # Отримання user_id з сесії
        user_id = session.get('user_id')
        logging.debug(f"Clear Cart: Retrieved user_id={user_id} from session.")

        if not user_id:
            flash("User is not authenticated.", "error")
            return redirect(url_for('index'))

        # Встановлення з'єднання з базою
        conn = get_db_connection()
        cursor = conn.cursor()

        # Видалення всіх елементів з кошика користувача
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        rows_deleted = cursor.rowcount  # Перевірка кількості видалених рядків
        conn.commit()

        logging.info(f"Cart cleared for user_id={user_id}. Rows deleted: {rows_deleted}")
        flash("Cart cleared successfully.", "success")
    except Exception as e:
        logging.error(f"Error clearing cart for user_id={user_id}: {e}", exc_info=True)
        flash("Error clearing cart.", "error")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()

    # Використання правильного ендпоінта для перенаправлення
    try:
        return redirect(url_for('cart', token=token))
    except Exception as e:
        logging.error(f"Error redirecting to cart for user_id={user_id}: {e}", exc_info=True)
        flash("Could not load your cart. Please try again.", "error")
        return redirect(url_for('index'))








# Оформлення замовлення
@app.route('/<token>/place_order', methods=['POST'])
@requires_token_and_role('user')
def place_order(token):
    try:
        user_id = session.get('user_id')  # Отримати ID поточного користувача з сесії
        logging.debug(f"Placing order for user_id={user_id}")

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            logging.error("Attempt to place order by unauthenticated user.")
            return redirect(url_for('index'))

        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримання товарів із кошика
        logging.debug("Fetching cart items...")
        cursor.execute("""
            SELECT c.product_id, p.price, c.quantity, c.comment
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        if not cart_items:
            flash("Your cart is empty!", "error")
            logging.warning(f"Cart is empty for user_id={user_id}.")
            return redirect(request.referrer or url_for('cart'))

        # Логування вмісту кошика
        logging.debug(f"Fetched cart items for user_id={user_id}: {cart_items}")
        for item in cart_items:
            logging.debug(f"Item details - product_id: {item['product_id']}, price: {item['price']}, quantity: {item['quantity']}, comment: {item.get('comment')}")

        # Розрахунок загальної суми
        total_price = sum(item['price'] * item['quantity'] for item in cart_items)
        logging.debug(f"Calculated total price for order: {total_price}")

        # Вставка замовлення в таблицю orders зі статусом "Pending"
        logging.debug("Inserting new order into orders table...")
        cursor.execute("""
            INSERT INTO orders (user_id, total_price, order_date, status)
            VALUES (%s, %s, NOW(), %s)
            RETURNING id
        """, (user_id, total_price, "Pending"))
        order_id = cursor.fetchone()['id']
        logging.info(f"Order created with id={order_id} for user_id={user_id}")

        # Вставка деталей замовлення
        logging.debug("Inserting order details into order_details table...")
        for item in cart_items:
            logging.debug(f"Inserting detail for product_id={item['product_id']}, order_id={order_id}...")
            cursor.execute("""
                INSERT INTO order_details (order_id, product_id, price, quantity, total_price, comment)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (order_id, item['product_id'], item['price'], item['quantity'], item['price'] * item['quantity'], item.get('comment')))
            logging.info(f"Inserted order detail: order_id={order_id}, product_id={item['product_id']}")

        # Очищення кошика
        logging.debug(f"Clearing cart for user_id={user_id}...")
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()
        logging.info(f"Cart cleared and order placed successfully for user_id={user_id}")

        flash("Order placed successfully!", "success")
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
    article_filter = request.args.get('article', '').strip()
    status_filter = request.args.get('status', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    # Логування отриманих фільтрів
    logging.debug(f"Received filters: Article: {article_filter}, Status: {status_filter}, Start Date: {start_date}, End Date: {end_date}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Початковий запит до таблиці orders
        query = """
        SELECT * FROM orders
        WHERE user_id = %s
        """
        params = [user_id]

        # Якщо фільтр по артикулу
        if article_filter:
            query += """
            AND EXISTS (
                SELECT 1 
                FROM order_items 
                WHERE order_id = orders.id 
                AND article LIKE %s
            )
            """
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

        # Додаємо сортування
        query += " ORDER BY order_date DESC"

        # Логування сформованого запиту
        logging.debug(f"Executing query: {query} with params: {params}")

        # Виконання запиту
        cursor.execute(query, params)
        orders = cursor.fetchall()

        logging.debug(f"Orders retrieved for user_id={user_id} with filters: {article_filter}, {status_filter}, {start_date}, {end_date}")

        return render_template('orders.html', orders=orders)

    except Exception as e:
        logging.error(f"Error fetching orders: {e}", exc_info=True)
        flash("Error fetching orders.", "error")
        return redirect(url_for('orders', token=token))

    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
        logging.debug("Database connection closed.")




# Окреме замовлення пористувача по id
@app.route('/<token>/order_details/<int:order_id>')
@requires_token_and_role('user') 
def order_details(token, order_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Отримання деталей замовлення з урахуванням коментарів
        cursor.execute("""
            SELECT od.order_id, p.article, od.price, od.quantity, od.total_price, od.comment
            FROM order_details od
            JOIN products p ON od.product_id = p.id
            WHERE od.order_id = %s
        """, (order_id,))
        details = cursor.fetchall()

        # Логування результатів запиту
        logging.debug(f"Order details fetched for order_id={order_id}: {details}")

        if not details:
            logging.warning(f"No details found for order_id={order_id}")
            flash("No details found for this order.", "warning")
            return render_template('order_details.html', details=[])

        # Рендеринг сторінки з переданими деталями
        return render_template('order_details.html', token=token, details=details)

    except Exception as e:
        logging.error(f"Error loading order details for order_id={order_id}: {str(e)}", exc_info=True)
        flash("Error loading order details. Please try again.", "error")
        return redirect(request.referrer or url_for('orders', token=token))
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        logging.debug(f"Database connection closed after fetching order details for order_id={order_id}")


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


@app.route('/<token>/upload_file', methods=['POST'])
@requires_token_and_role('user')
def upload_file(token):
    """
    Завантажує файл із товарами, обробляє його та виконує точний збіг для артикула.
    """
    logging.debug(f"Upload File Called with token: {token}")
    try:
        # Отримання ID користувача
        user_id = session.get('user_id')
        if not user_id:
            logging.error("User not authenticated.")
            flash("User not authenticated", "error")
            return redirect(f'/{token}/')

        logging.info(f"User ID: {user_id} started file upload.")

        # Перевірка наявності файлу
        if 'file' not in request.files:
            logging.error("No file uploaded.")
            flash("No file uploaded", "error")
            return redirect(f'/{token}/')

        file = request.files['file']
        logging.info(f"Uploaded file: {file.filename}")

        # Перевірка формату файлу
        if not file.filename.endswith('.xlsx'):
            logging.error("Invalid file format. Only .xlsx files are allowed.")
            flash("Invalid file format. Please upload an Excel file.", "error")
            return redirect(f'/{token}/')

        # Завантаження даних з файлу
        try:
            df = pd.read_excel(file, header=None)  # Завантаження без заголовків
            logging.info(f"File read successfully. Shape: {df.shape}")
        except Exception as e:
            logging.error(f"Error reading Excel file: {e}", exc_info=True)
            flash("Error reading the file. Please check the format.", "error")
            return redirect(f'/{token}/')

        # Перевірка мінімальної кількості колонок
        if df.shape[1] < 2:
            logging.error("Invalid file structure. Less than two columns found.")
            flash("Invalid file structure. Ensure the file has at least two columns.", "error")
            return redirect(f'/{token}/')

        # Заповнення відсутніх колонок значенням None
        for col in range(2, 4):
            if df.shape[1] <= col:
                df[col] = None

        logging.debug(f"Dataframe after preprocessing: {df.head()}")

        items_with_table = []      # Артикули з таблицею
        items_without_table = []   # Артикули без таблиці
        missing_articles = set()   # Унікальні відсутні артикули

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Отримання всіх таблиць з price_lists
            cursor.execute("SELECT table_name FROM price_lists;")
            all_tables = [row[0] for row in cursor.fetchall()]
            logging.info(f"Fetched tables from price_lists: {all_tables}")

            for index, row in df.iterrows():
                try:
                    article = str(row[0]).strip()
                    quantity = int(row[1])
                    table_name = str(row[2]).strip() if pd.notna(row[2]) else None
                    comment = str(row[3]).strip() if pd.notna(row[3]) else None

                    if table_name:
                        if table_name not in all_tables:
                            logging.warning(f"Invalid table name '{table_name}' for article {article}.")
                            missing_articles.add(article)
                            continue

                        cursor.execute(f"SELECT article, price FROM {table_name} WHERE article = %s", (article,))
                        result = cursor.fetchone()
                        if result:
                            price = result[1]
                            items_with_table.append((article, price, table_name, quantity, comment))
                        else:
                            missing_articles.add(article)
                            logging.warning(f"Article {article} not found in {table_name}.")
                    else:
                        matching_tables = []
                        for table in all_tables:
                            cursor.execute(f"SELECT article FROM {table} WHERE article = %s", (article,))
                            if cursor.fetchone():
                                matching_tables.append(table)

                        if matching_tables:
                            items_without_table.append((article, quantity, matching_tables, comment))
                        else:
                            missing_articles.add(article)
                            logging.warning(f"Article {article} not found in any table.")
                except Exception as e:
                    logging.error(f"Error processing row at index {index}: {row.tolist()} - {e}")

        logging.debug(f"Items with table: {items_with_table}")
        logging.debug(f"Items without table: {items_without_table}")
        logging.debug(f"Missing articles: {list(missing_articles)}")

        # Додавання до кошика артикулів із таблицею
        for article, price, table_name, quantity, comment in items_with_table:
            if not price or not table_name:
                logging.warning(f"Skipping article {article} with missing price or table_name.")
                continue
            cursor.execute(
                """
                INSERT INTO cart (user_id, product_id, quantity, added_at, comment)
                VALUES (
                    %s,
                    (SELECT id FROM products WHERE article = %s AND table_name = %s),
                    %s,
                    NOW(),
                    %s
                )
                ON CONFLICT (user_id, product_id) DO UPDATE SET
                quantity = cart.quantity + EXCLUDED.quantity,
                comment = EXCLUDED.comment
                """,
                (user_id, article, table_name, quantity, comment)
            )
            logging.info(f"Added article {article} to cart from table {table_name}.")

        conn.commit()
        logging.info("Database operations committed successfully.")

        # Формування повідомлення для користувача
        if items_without_table:
            session['items_without_table'] = items_without_table
            flash(f"{len(items_without_table)} articles need table selection.", "warning")
            logging.info(f"Redirecting to intermediate_results. Items without table: {len(items_without_table)}")
            return redirect(url_for('intermediate_results', token=token))

        if missing_articles:
            session['missing_articles'] = list(missing_articles)
            flash(f"The following articles were not found: {', '.join(missing_articles)}", "warning")
            logging.info(f"Missing articles: {missing_articles}")

        flash(f"File processed successfully. {len(items_with_table)} items added to cart. {len(missing_articles)} missing articles.", "success")
        logging.info(f"File processed successfully for user_id={user_id}.")
        return redirect(url_for('cart', token=token))

    except Exception as e:
        logging.error(f"Error in upload_file: {e}", exc_info=True)
        flash("An error occurred during file upload. Please try again.", "error")
        return redirect(f'/{token}/')



@app.route('/<token>/intermediate_results', methods=['GET', 'POST'])
@requires_token_and_role('user')
def intermediate_results(token):
    """
    Обробляє статті без таблиці, надає можливість вибрати таблиці,
    а потім додає вибрані статті до таблиці `products` і кошика.
    """
    logging.debug(f"Intermediate Results Called with token: {token}")
    try:
        # Ідентифікація користувача
        user_id = session.get('user_id')
        if not user_id:
            logging.error("User not authenticated.")
            flash("User not authenticated", "error")
            return redirect(f'/{token}/')

        # Отримання націнки
        user_markup = get_markup_percentage(user_id)
        logging.debug(f"Markup percentage for user_id={user_id}: {user_markup}%")

        if request.method == 'POST':
            logging.info("Processing user table selection for articles.")
            # Отримання вибору користувача
            user_selections = {
                key.split('_')[1]: value
                for key, value in request.form.items() if key.startswith('table_')
            }
            logging.debug(f"User selections: {user_selections}")

            items_without_table = session.get('items_without_table', [])
            missing_articles = session.get('missing_articles', [])
            added_to_cart = []

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    for article, quantity, valid_tables, comment in items_without_table:
                        selected_table = user_selections.get(article)
                        if not selected_table or selected_table not in valid_tables:
                            if article not in missing_articles:
                                missing_articles.append(article)
                            logging.warning(f"Invalid or missing table for article {article}. Selected table: {selected_table}")
                            continue

                        try:
                            cursor.execute(
                                "SELECT price FROM {} WHERE article = %s".format(selected_table),
                                (article,)
                            )
                            result = cursor.fetchone()
                        except Exception as e:
                            logging.error(f"Error querying table {selected_table} for article {article}: {e}")
                            missing_articles.append(article)
                            continue

                        if result:
                            base_price = Decimal(result[0])
                            final_price = round(base_price * (1 + user_markup / 100), 2)

                            # Перевірка існування у `products`
                            cursor.execute(
                                "SELECT id FROM products WHERE article = %s AND table_name = %s",
                                (article, selected_table)
                            )
                            product = cursor.fetchone()

                            if not product:
                                cursor.execute(
                                    """
                                    INSERT INTO products (article, price, table_name, created_at)
                                    VALUES (%s, %s, %s, NOW())
                                    RETURNING id
                                    """,
                                    (article, base_price, selected_table)
                                )
                                product_id = cursor.fetchone()[0]
                                logging.info(f"Article {article} added to products with base price {base_price} in table {selected_table}.")
                            else:
                                product_id = product[0]

                            cursor.execute(
                                """
                                INSERT INTO cart (user_id, product_id, quantity, base_price, final_price, added_at, comment)
                                VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                                ON CONFLICT (user_id, product_id) DO UPDATE SET
                                quantity = cart.quantity + EXCLUDED.quantity,
                                final_price = EXCLUDED.final_price,
                                comment = EXCLUDED.comment
                                """,
                                (user_id, product_id, quantity, base_price, final_price, comment)
                            )
                            added_to_cart.append(article)
                            logging.info(f"Article {article} added to cart from table {selected_table}.")
                        else:
                            logging.warning(f"Article {article} not found in table {selected_table}. Skipping.")

                    conn.commit()
                    logging.info("Database operations committed successfully.")

            # Оновлення сесії
            session['items_without_table'] = [
                item for item in items_without_table if item[0] not in added_to_cart
            ]
            session['missing_articles'] = list(set(missing_articles))
            logging.debug(f"Session updated. Missing articles: {session['missing_articles']}")

            if session['items_without_table']:
                flash("Some articles still need a table. Please review.", "warning")
                return redirect(url_for('intermediate_results', token=token))

            flash("All selected articles have been added to your cart.", "success")
            return redirect(url_for('cart', token=token))

        # GET: Відображення проміжних результатів
        items_without_table = session.get('items_without_table', [])
        missing_articles = session.get('missing_articles', [])
        logging.debug(f"Rendering intermediate results. items_without_table={len(items_without_table)}, missing_articles={len(missing_articles)}")

        enriched_items = []
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                for article, quantity, valid_tables, comment in items_without_table:
                    item_prices = []
                    for table in valid_tables:
                        cursor.execute(
                            "SELECT price FROM {} WHERE article = %s".format(table),
                            (article,)
                        )
                        result = cursor.fetchone()
                        if result:
                            final_price = round(Decimal(result[0]) * (1 + user_markup / 100), 2)
                            item_prices.append({'table': table, 'final_price': final_price})
                    enriched_items.append({
                        'article': article,
                        'quantity': quantity,
                        'valid_tables': valid_tables,
                        'prices': item_prices,
                        'comment': comment
                    })

        # Передача всіх даних у шаблон
        return render_template(
            'intermediate.html',
            token=token,
            items_without_table=enriched_items,
            missing_articles=missing_articles
        )

    except Exception as e:
        logging.error(f"Error in intermediate_results: {e}", exc_info=True)
        flash("An error occurred while processing your selection. Please try again.", "error")
        return redirect(f'/{token}/')



def get_markup_percentage(user_id):
    """
    Отримує відсоток націнки для користувача за його роллю.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.markup_percentage
                FROM user_roles ur
                JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = %s
            """, (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 35  # За замовчуванням 35%
    except Exception as e:
        logging.error(f"Error fetching markup percentage for user_id={user_id}: {e}", exc_info=True)
        return 35  # Повертає стандартну націнку у разі помилки


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
