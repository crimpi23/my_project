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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

# Налаштування логування
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# Додаємо фільтр для кольорів статусу замовлення
@app.template_filter('status_color')
def status_color(status):
    # Мапінг статусів до кольорів Bootstrap
    colors = {
        'new': 'primary',
        'pending': 'warning',
        'accepted': 'success',
        'rejected': 'danger',
        'cancelled': 'secondary'
    }
    return colors.get(status.lower(), 'secondary')

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
def requires_token_and_roles(*allowed_roles):
    """
    Декоратор для перевірки токена і декількох дозволених ролей користувача.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(token, *args, **kwargs):
            logging.debug(f"Session token: {session.get('token')}")
            logging.debug(f"Received token: {token}")
            
            # Перевірка відповідності токену
            if session.get('token') != token:
                flash("Access denied. Token mismatch.", "error")
                return redirect(url_for('index'))

            # Отримання даних ролі
            role_data = validate_token(token)
            logging.debug(f"Role data from token: {role_data}")
            
            if not role_data or role_data['role'] not in allowed_roles:
                flash("Access denied. Insufficient permissions.", "error")
                return redirect(url_for('index'))

            # Збереження даних користувача в сесії
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
            session['user_id'] = result['user_id']
            session['role'] = result['role']  # зберігаємо тільки назву ролі
            logging.debug(f"User ID: {result['user_id']}, Role: {result['role']}")

        conn.close()
        return result if result else None
    except Exception as e:
        logging.error(f"Error validating token: {e}")
        return None


def send_email(to_email, subject, ordered_items, missing_articles):
    """
    Відправляє повідомлення на вказану електронну адресу з деталями замовлення.
    """
    try:
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        sender_email = os.getenv("SMTP_EMAIL")  # Отримання адреси з environment variables
        sender_password = os.getenv("SMTP_PASSWORD")  # Отримання пароля з environment variables

        if not sender_email or not sender_password:
            raise ValueError("SMTP credentials are not set in environment variables.")

        # Формування тексту повідомлення
        message_body = f"Thank you for your order!\n\nYour order details:\n"

        if ordered_items:
            message_body += "Ordered items:\n"
            for item in ordered_items:
                message_body += (
                    f"- Article: {item['article']}, "
                    f"Price: {item['price']:.2f}, "
                    f"Quantity: {item['quantity']}, "
                    f"Comment: {item['comment'] or 'No comment'}\n"
                )
        
        if missing_articles:
            message_body += "\nMissing articles:\n"
            for article in missing_articles:
                message_body += f"- {article}\n"

        # Формування повідомлення
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(message_body, "plain"))

        # Відправка через SMTP
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)

        logging.info(f"Email sent successfully to {to_email}")
    except Exception as e:
        logging.error(f"Failed to send email to {to_email}: {e}")


# Функція для визначення розділювача у рядку
def detect_delimiter(line):
    delimiters = ['\t', ' ', ';', ',']
    for delimiter in delimiters:
        if delimiter in line:
            return delimiter
    return '\t'


# Функція для розбору рядка з артикулом
def parse_article_line(line, available_tables):
    delimiter = detect_delimiter(line)
    parts = line.strip().split(delimiter)

    # Базові параметри
    article = parts[0].strip().upper()
    quantity = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 1

    # Перевірка третього параметра
    if len(parts) > 2:
        if parts[2].strip().lower() in available_tables:
            specified_table = parts[2].strip().lower()
            comment = parts[3].strip() if len(parts) > 3 else None
        else:
            specified_table = None
            comment = parts[2].strip()
    else:
        specified_table = None
        comment = None

    return {
        'article': article,
        'quantity': quantity,
        'specified_table': specified_table,
        'comment': comment
    }

def send_order_confirmation_email(to_email, order_id, total_price, cart_items):
    try:
        smtp_server = current_app.config['SMTP_SERVER']
        smtp_port = current_app.config['SMTP_PORT']
        smtp_username = current_app.config['SMTP_USERNAME']
        smtp_password = current_app.config['SMTP_PASSWORD']

        # Формування листа
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = to_email
        msg['Subject'] = f"Order Confirmation #{order_id}"

        # Тіло листа
        items_list = "".join([f"- {item['quantity']}x {item['product_id']} at ${item['price']}\n" for item in cart_items])
        body = f"""
        Dear Customer,

        Thank you for your order #{order_id}!

        Order Summary:
        {items_list}
        Total Price: ${total_price}

        Best regards,
        MySite Team
        """
        msg.attach(MIMEText(body, 'plain'))

        # Підключення до SMTP і надсилання
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        logging.info(f"Order confirmation email sent to {to_email} for order #{order_id}")
    except Exception as e:
        logging.error(f"Failed to send email to {to_email}: {e}", exc_info=True)


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

# Доступ до адмін панелі
@app.route('/<token>/admin', methods=['GET', 'POST'])
def admin_panel(token):
    try:
        logging.debug(f"Token received in admin_panel: {token}")

        # Валідація токена
        role_data = validate_token(token)
        logging.debug(f"Role data after validation: {role_data}")

        if not role_data or role_data['role'] != 'admin':
            logging.warning(f"Access denied for token: {token}, Role data: {role_data}")
            flash("Access denied. Admin rights are required.", "error")
            return redirect(url_for('simple_search'))

        # Збереження даних сесії
        session['token'] = token
        session['user_id'] = role_data['user_id']
        session['role'] = role_data['role']
        logging.debug(f"Session after saving role: {dict(session)}")

        # Обробка POST-запиту
        if request.method == 'POST':
            password = request.form.get('password')
            logging.debug(f"Password entered: {'******' if password else 'None'}")

            if not password:
                flash("Password is required.", "error")
                return redirect(url_for('admin_panel', token=token))

            conn = get_db_connection()
            cursor = conn.cursor()

            # Перевірка пароля адміністратора
            cursor.execute("""
                SELECT password_hash 
                FROM users
                WHERE id = %s
            """, (role_data['user_id'],))
            admin_password_hash = cursor.fetchone()
            logging.debug(f"Fetched admin password hash: {admin_password_hash}")

            if not admin_password_hash or not verify_password(password, admin_password_hash[0]):
                logging.warning("Invalid admin password attempt.")
                flash("Invalid password.", "error")
                return redirect(url_for('admin_panel', token=token))

            # Встановлення статусу автентифікації
            session['admin_authenticated'] = True
            session.modified = True
            logging.info(f"Admin authenticated for token: {token}")

            return redirect(url_for('admin_dashboard', token=token))

        # Відображення форми входу
        return render_template('admin_login.html', token=token)

    except Exception as e:
        logging.error(f"Error in admin_panel: {e}", exc_info=True)
        flash("An error occurred while accessing the admin panel.", "error")
        return redirect(url_for('simple_search'))

    finally:
        if 'conn' in locals() and conn:
            conn.close()


# Головна сторінка адмінки
@app.route('/<token>/admin/dashboard')
@requires_token_and_roles('admin')
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
@requires_token_and_roles('admin')
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







# @app.route('/process_selection', methods=['POST'])
# @requires_token_and_roles('user', 'user_25', 'user_29')
# def process_selection():
    # try:
        # selected_prices = {}
        # for key, value in request.form.items():
            # if key.startswith('selected_price_'):
                # article = key.replace('selected_price_', '')
                # table_name, price = value.split(':')
                # selected_prices[article] = {'table_name': table_name, 'price': float(price)}

        # user_id = session.get('user_id')
        # if not user_id:
            # flash("User is not authenticated.", "error")
            # return redirect(url_for('index'))

        # Очищення старих записів і додавання нових
        # with get_db_connection() as conn:
            # with conn.cursor() as cursor:
                # cursor.execute("DELETE FROM selection_buffer WHERE user_id = %s", (user_id,))

                # for article, data in selected_prices.items():
                    # cursor.execute("""
                        # INSERT INTO selection_buffer (user_id, article, table_name, price, quantity, added_at)
                        # VALUES (%s, %s, %s, %s, 1, NOW());
                    # """, (user_id, article, data['table_name'], data['price']))

        # flash("Ваш вибір успішно збережено!", "success")
    # except Exception as e:
        # logging.error(f"Error processing selection: {str(e)}")
        # flash("Сталася помилка при обробці вибору. Спробуйте ще раз.", "error")

    # return redirect(url_for('search_results'))


@app.route('/<token>/search', methods=['GET', 'POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def search_articles(token):
    try:
        articles_input = request.form.get('articles', '').strip()
        if not articles_input:
            flash("Please enter at least one article.", "error")
            return redirect(url_for('index'))

        # Створюємо множини для порівняння артикулів
        requested_articles = set()
        articles_data = []
        quantities = {}
        comments = {}

        # Отримуємо список доступних таблиць спочатку
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM price_lists")
            available_tables = [row[0] for row in cursor.fetchall()]

        for line in articles_input.splitlines():
            delimiter = detect_delimiter(line)
            parts = line.strip().split(delimiter)
            if len(parts) == 0:
                continue

            article = parts[0].strip().upper()
            requested_articles.add(article)

            quantity = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1

            # Перевіряємо третій параметр
            if len(parts) > 2:
                if parts[2].strip().lower() in available_tables:
                    specified_table = parts[2].strip().lower()
                    comment = parts[3].strip() if len(parts) > 3 else None
                else:
                    specified_table = None
                    comment = parts[2].strip()
            else:
                specified_table = None
                comment = None

            quantities[article] = quantity
            comments[article] = comment
            articles_data.append({
                'article': article,
                'quantity': quantity,
                'specified_table': specified_table,
                'comment': comment
            })

        with get_db_connection() as conn:
            cursor = conn.cursor()
            user_markup = Decimal(get_markup_percentage(session['user_id']))

            to_add_to_cart = []
            multiple_prices = {}
            found_articles = set()

            for item in articles_data:
                article = item['article']
                specified_table = item['specified_table']

                if specified_table:
                    if specified_table not in available_tables:
                        continue

                    cursor.execute(f"SELECT price FROM {specified_table} WHERE article = %s", (article,))
                    result = cursor.fetchone()

                    if result:
                        found_articles.add(article)
                        base_price = Decimal(result[0])
                        final_price = round(base_price * (1 + user_markup / 100), 2)
                        to_add_to_cart.append({
                            'article': article,
                            'table': specified_table,
                            'price': base_price,
                            'final_price': final_price,
                            'quantity': item['quantity'],
                            'comment': item['comment']
                        })
                else:
                    prices_found = []
                    for table in available_tables:
                        cursor.execute(f"SELECT price FROM {table} WHERE article = %s", (article,))
                        result = cursor.fetchone()
                        if result:
                            found_articles.add(article)
                            base_price = Decimal(result[0])
                            final_price = round(base_price * (1 + user_markup / 100), 2)
                            prices_found.append({
                                'table_name': table,
                                'base_price': base_price,
                                'price': final_price,
                                'quantity': item['quantity'],
                                'comment': item['comment']
                            })

                    if len(prices_found) > 1:
                        multiple_prices[article] = prices_found
                    elif len(prices_found) == 1:
                        price_info = prices_found[0]
                        to_add_to_cart.append({
                            'article': article,
                            'table': price_info['table_name'],
                            'price': price_info['base_price'],
                            'final_price': price_info['price'],
                            'quantity': item['quantity'],
                            'comment': item['comment']
                        })

            # Визначаємо відсутні артикули
            missing_articles = list(requested_articles - found_articles)

            if missing_articles:
                flash(f"Articles not found: {', '.join(missing_articles)}", "warning")

            # Додаємо в кошик артикули з однією таблицею
            if to_add_to_cart:
                for item in to_add_to_cart:
                    cursor.execute("""
                        INSERT INTO cart 
                        (user_id, article, table_name, quantity, base_price, final_price, comment, added_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id, article, table_name) 
                        DO UPDATE SET 
                            quantity = cart.quantity + EXCLUDED.quantity,
                            final_price = EXCLUDED.final_price,
                            comment = EXCLUDED.comment
                    """, (
                        session['user_id'],
                        item['article'],
                        item['table'],
                        item['quantity'],
                        item['price'],
                        item['final_price'],
                        item['comment']
                    ))
                conn.commit()
                flash(f"Added to cart: {', '.join(item['article'] for item in to_add_to_cart)}", "success")

            # Зберігаємо дані в сесії для артикулів з multiple_prices
            session['grouped_results'] = multiple_prices
            session['missing_articles'] = missing_articles

            # Якщо є артикули для вибору таблиць
            if multiple_prices:
                return render_template(
                    'search_results.html',
                    grouped_results=multiple_prices,
                    missing_articles=missing_articles,
                    quantities=quantities,
                    comments=comments,
                    token=token
                )

            # Якщо всі артикули оброблені - перенаправляємо в кошик
            return redirect(url_for('cart', token=token))

    except Exception as e:
        logging.error(f"Error in search_articles: {str(e)}", exc_info=True)
        flash("An error occurred during search. Please try again.", "error")
        return redirect(url_for('index'))


@app.route('/<token>/search_results', methods=['GET', 'POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def search_results(token):
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to view search results.", "error")
        return redirect(url_for('index'))

    # Якщо це POST-запит, обробляємо вибір користувача
    if request.method == 'POST':
        selected_prices = {}
        for key, value in request.form.items():
            if key.startswith('selected_price_'):
                article = key.replace('selected_price_', '')
                table_name, price = value.split(':')
                selected_prices[article] = {
                    'table_name': table_name,
                    'price': Decimal(price),
                }

        # Зберегти вибір у `selection_buffer`
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Очистити буфер для поточного користувача
            cursor.execute("DELETE FROM selection_buffer WHERE user_id = %s", (user_id,))

            # Додати нові записи
            for article, data in selected_prices.items():
                cursor.execute("""
                    INSERT INTO selection_buffer (user_id, article, table_name, price, quantity, added_at)
                    VALUES (%s, %s, %s, %s, 1, NOW())
                """, (user_id, article, data['table_name'], data['price']))

            conn.commit()
            flash("Your selection has been saved!", "success")
        except Exception as e:
            conn.rollback()
            logging.error(f"Error updating selection buffer: {str(e)}", exc_info=True)
            flash("An error occurred while saving your selection. Please try again.", "error")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('search_results', token=token))

    # Якщо це GET-запит, відображаємо результати
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Отримати список прайс-листів
        cursor.execute("SELECT table_name FROM price_lists")
        price_list_tables = [row[0] for row in cursor.fetchall()]

        # Отримати артикул із сесії
        grouped_results = session.get('grouped_results', {})
        if not grouped_results:
            flash("No search results found. Please start a new search.", "info")
            return redirect(url_for('index'))

        # Групувати результати по артикулах
        results = {}
        for article, options in grouped_results.items():
            for option in options:
                results.setdefault(article, []).append(option)

        return render_template(
            'search_results.html',
            grouped_results=results,
            token=token
        )

    except Exception as e:
        logging.error(f"Error fetching search results: {str(e)}", exc_info=True)
        flash("An error occurred while retrieving search results.", "error")
        return redirect(url_for('index'))
    finally:
        cursor.close()
        conn.close()
 
 
 
@app.route('/<token>/cart', methods=['GET', 'POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
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
            article = request.form.get('article')
            table_name = request.form.get('table_name')
            logging.debug(f"POST action received: {action}, article: {article}, table_name: {table_name}")

            if action == 'remove' and article and table_name:
                # Видалення товару з кошика
                cursor.execute(
                    """
                    DELETE FROM cart
                    WHERE user_id = %s AND article = %s AND table_name = %s
                    """,
                    (user_id, article, table_name)
                )
                conn.commit()
                flash("Item removed from cart.", "success")
                logging.info(f"Article {article} removed from cart for user_id {user_id}.")

            elif action == 'update_quantity' and article and table_name:
                # Оновлення кількості товару
                try:
                    new_quantity = int(request.form.get('quantity', 1))
                    if new_quantity > 0:
                        cursor.execute(
                            """
                            UPDATE cart
                            SET quantity = %s
                            WHERE user_id = %s AND article = %s AND table_name = %s
                            """,
                            (new_quantity, user_id, article, table_name)
                        )
                        conn.commit()
                        flash("Item quantity updated.", "success")
                        logging.info(f"Article {article} quantity updated to {new_quantity} for user_id {user_id}.")
                    else:
                        flash("Quantity must be greater than zero.", "error")
                        logging.warning(f"Invalid quantity {new_quantity} provided for article {article}.")
                except ValueError:
                    flash("Invalid quantity provided.", "error")
                    logging.error(f"Non-integer quantity provided for article {article}.")

        # Отримуємо товари з кошика
        cursor.execute("""
            SELECT 
                article, 
                table_name, 
                COALESCE(base_price, 0) AS base_price,
                COALESCE(final_price, 0) AS final_price,
                quantity,
                ROUND(COALESCE(final_price, 0) * quantity, 2) AS total_price,
                comment
            FROM cart
            WHERE user_id = %s
            ORDER BY added_at ASC, article ASC, table_name ASC
        """, (user_id,))

        cart_items = []
        for row in cursor.fetchall():
            cart_items.append({
                'article': row['article'],
                'table_name': row['table_name'],
                'base_price': float(row['base_price']),
                'final_price': float(row['final_price']),
                'quantity': row['quantity'],
                'total_price': float(row['total_price']),
                'comment': row['comment']
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




#проміжковий єтап перед search, який минує search_results до cart
@app.route('/<token>/submit_selection', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def submit_selection(token):
    """
    Обробляє вибір користувача та додає вибрані артикули в кошик безпосередньо.
    """
    logging.debug(f"Submit Selection Called with token: {token}")
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash("User not authenticated", "error")
            logging.warning("User not authenticated. Redirecting to search.")
            return redirect(url_for('search_articles', token=token))

        # Обробка даних із форми
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

        # Підключення до бази даних
        with get_db_connection() as conn:
            cursor = conn.cursor()

            for article, price, table_name, quantity, comment in selected_articles:
                try:
                    # Додавання товару в кошик
                    cursor.execute(
                        """
                        INSERT INTO cart (user_id, article, table_name, quantity, base_price, final_price, comment, added_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id, article, table_name) DO UPDATE SET
                        quantity = cart.quantity + EXCLUDED.quantity,
                        final_price = EXCLUDED.final_price,
                        comment = EXCLUDED.comment
                        """,
                        (user_id, article, table_name, quantity, price, price, comment)
                    )
                    logging.info(f"Article {article} added/updated in cart for user_id={user_id}.")
                except Exception as e:
                    logging.error(f"Error adding article {article} to cart: {e}")
                    flash(f"Error adding article {article} to cart.", "error")
                    continue

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
@requires_token_and_roles('user', 'user_25', 'user_29')
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
# Додавання в кошик користувачем
@app.route('/<token>/add_to_cart', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def add_to_cart(token):
    """
    Додає товар до кошика користувача.
    """
    conn = None
    cursor = None
    try:
        # Отримання даних з форми
        article = request.form.get('article')
        price = Decimal(request.form.get('price'))  # Ціна на момент додавання
        quantity = int(request.form.get('quantity'))  # Кількість товару
        table_name = request.form.get('table_name')
        comment = request.form.get('comment', None)  # Коментар користувача
        user_id = session.get('user_id')  # ID користувача

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            return redirect(url_for('index'))

        logging.debug(f"Adding to cart: Article={article}, Price={price}, Quantity={quantity}, Table={table_name}, User={user_id}")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Перевірка, чи товар вже є в кошику
        cursor.execute("""
            SELECT id, quantity FROM cart
            WHERE user_id = %s AND article = %s AND table_name = %s
        """, (user_id, article, table_name))
        existing_cart_item = cursor.fetchone()

        if existing_cart_item:
            # Оновлення кількості товару в кошику
            new_quantity = existing_cart_item['quantity'] + quantity
            cursor.execute("""
                UPDATE cart
                SET quantity = %s
                WHERE id = %s
            """, (new_quantity, existing_cart_item['id']))
            logging.info(f"Cart updated: Article={article}, New Quantity={new_quantity}, User ID={user_id}")
        else:
            # Додавання нового товару в кошик
            cursor.execute("""
                INSERT INTO cart (user_id, article, table_name, price, quantity, comment, added_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (user_id, article, table_name, price, quantity, comment))
            logging.info(f"Product added to cart: Article={article}, Quantity={quantity}, User ID={user_id}")

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
@requires_token_and_roles('user', 'user_25', 'user_29')
def remove_from_cart(token):
    try:
        user_id = session.get('user_id')
        article = request.form.get('article')
        table_name = request.form.get('table_name')

        logging.debug(f"Removing from cart: Article={article}, Table={table_name}, User={user_id}")

        if not all([user_id, article, table_name]):
            flash("Missing required information for removal", "error")
            return redirect(url_for('cart', token=token))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM cart 
                WHERE user_id = %s 
                AND article = %s 
                AND table_name = %s
                RETURNING id
            """, (user_id, article, table_name))

            deleted = cursor.fetchone()
            conn.commit()

            if deleted:
                flash(f"Article {article} removed successfully", "success")
                logging.info(f"Article {article} removed from cart for user_id={user_id}")
            else:
                flash("Item not found in cart", "warning")
                logging.warning(f"Failed to remove article {article} for user_id={user_id}")

    except Exception as e:
        logging.error(f"Error removing from cart: {e}", exc_info=True)
        flash("Error removing item from cart", "error")

    return redirect(url_for('cart', token=token))


# Оновлення товару в кошику
@app.route('/<token>/update_cart', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def update_cart(token):
    """
    Оновлює кількість товарів у кошику.
    """
    try:
        # Отримуємо дані з форми
        article = request.form.get('article')
        quantity = request.form.get('quantity')
        user_id = session['user_id']

        if not article or not quantity:
            flash("Invalid input: article or quantity missing.", "error")
            logging.error("Missing article or quantity in update_cart form.")
            return redirect(url_for('cart', token=token))

        quantity = int(quantity)

        if quantity < 1:
            flash("Quantity must be at least 1.", "error")
            logging.error(f"Invalid quantity: {quantity}")
            return redirect(url_for('cart', token=token))

        logging.debug(f"Updating cart: Article={article}, Quantity={quantity}, User={user_id}")

        conn = get_db_connection()
        cursor = conn.cursor()

        # Оновлення кількості у кошику
        cursor.execute("""
            UPDATE cart
            SET quantity = %s
            WHERE user_id = %s AND article = %s
        """, (quantity, user_id, article))

        conn.commit()
        flash("Cart updated successfully!", "success")

    except Exception as e:
        logging.error(f"Error updating cart: {e}", exc_info=True)
        flash("Error updating cart.", "error")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
        logging.debug("Database connection closed after updating cart.")

    return redirect(url_for('cart', token=token))


# Очищення кошика користувача
@app.route('/<token>/clear_cart', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def clear_cart(token):
    try:
        user_id = session.get('user_id')
        logging.debug(f"Clear Cart: Retrieved user_id={user_id} from session.")

        # Очищення кошика в базі даних
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        rows_deleted = cursor.rowcount
        conn.commit()

        logging.info(f"Cart cleared for user_id={user_id}. Rows deleted: {rows_deleted}")

        # Очищення даних сесії
        session_keys_to_clear = [
            'grouped_results',
            'quantities',
            'comments',
            'missing_articles',
            'items_without_table'
        ]

        for key in session_keys_to_clear:
            if key in session:
                session.pop(key)
                logging.debug(f"Session data '{key}' cleared for user_id={user_id}.")

        session.modified = True
        flash("Cart cleared successfully.", "success")

    except Exception as e:
        logging.error(f"Error clearing cart for user_id={user_id}: {e}", exc_info=True)
        flash("Error clearing cart.", "error")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()

    return redirect(url_for('cart', token=token))


# з кошика в замовлення
@app.route('/<token>/place_order', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def place_order(token):
    """
    Функція для обробки замовлення:
    - Створює замовлення в таблиці `orders`.
    - Додає деталі замовлення до `order_details`.
    - Очищає кошик користувача.
    - Відправляє підтвердження електронною поштою.
    """
    try:
        user_id = session.get('user_id')
        # Отримуємо відсутні артикули з сесії
        missing_articles = session.get('missing_articles', [])
        
        logging.debug(f"Placing order for user_id={user_id}")

        if not user_id:
            flash("User is not authenticated. Please log in.", "error")
            logging.error("Attempt to place order by unauthenticated user.")
            return redirect(url_for('index'))

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Отримання товарів з кошика
        logging.debug("Fetching cart items...")
        cursor.execute("""
            SELECT article, table_name, final_price as price, quantity, 
                   (final_price * quantity) as total_price, comment
            FROM cart 
            WHERE user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        if not cart_items:
            flash("Your cart is empty!", "error")
            logging.warning(f"Cart is empty for user_id={user_id}.")
            return redirect(request.referrer or url_for('cart'))

        # Підрахунок загальної суми
        total_price = sum(item['price'] * item['quantity'] for item in cart_items)
        logging.debug(f"Calculated total price for order: {total_price}")

        # Створення запису замовлення
        cursor.execute("""
            INSERT INTO orders (user_id, total_price, order_date, status)
            VALUES (%s, %s, NOW(), %s)
            RETURNING id
        """, (user_id, total_price, "Pending"))
        order_id = cursor.fetchone()['id']
        logging.info(f"Order created with id={order_id} for user_id={user_id}")

        # Додавання деталей замовлення
        ordered_items = []
        for cart_item in cart_items:
            # Додаємо запис в таблицю order_details
            cursor.execute("""
                INSERT INTO order_details 
                (order_id, article, table_name, price, quantity, total_price, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                order_id,
                cart_item['article'],
                cart_item['table_name'],
                cart_item['price'],
                cart_item['quantity'],
                cart_item['total_price'],
                cart_item['comment'] or "No comment"
            ))
            
            # Логуємо успішне додавання
            logging.info(f"Inserted order detail: order_id={order_id}, article={cart_item['article']}")
            
            # Зберігаємо інформацію про замовлений товар
            ordered_items.append({
                "article": cart_item['article'],
                "price": cart_item['price'],
                "quantity": cart_item['quantity'],
                "comment": cart_item['comment'] or "No comment",
                "table_name": cart_item['table_name']
            })

        # Очищення кошика
        logging.debug(f"Clearing cart for user_id={user_id}...")
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))

        # Підтвердження замовлення
        conn.commit()


        # Надсилання підтвердження на email
        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        user_email = cursor.fetchone()

        if user_email and 'email' in user_email and user_email['email']:
            try:
                send_email(
                    to_email=user_email['email'],
                    subject=f"Order Confirmation - Order #{order_id}",
                    ordered_items=ordered_items,
                    missing_articles=session.get('missing_articles', [])
                )
                logging.info(f"Email sent successfully to {user_email['email']}")
            except Exception as email_error:
                logging.error(f"Failed to send email: {email_error}")
                flash("Order placed, but we couldn't send a confirmation email.", "warning")

        # Очищаємо список відсутніх позицій
        session['missing_articles'] = []
        session.modified = True

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
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
        logging.debug("Database connection closed.")





# Замовлення користувача
@app.route('/<token>/orders', methods=['GET'])
@requires_token_and_roles('user', 'user_25', 'user_29')
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
                FROM order_details 
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



# Окреме замовлення користувача по id
@app.route('/<token>/order_details/<int:order_id>')
@requires_token_and_roles('user', 'user_25', 'user_29')
def order_details(token, order_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо деталі замовлення
        cursor.execute("""
            SELECT order_id, article, table_name, price, quantity, total_price, comment
            FROM order_details 
            WHERE order_id = %s
        """, (order_id,))
        details = cursor.fetchall()

        # Форматуємо дані
        formatted_details = [
            {
                'article': row[1],
                'table_name': row[2],
                'price': float(row[3]),
                'quantity': row[4],
                'total_price': float(row[5]),
                'comment': row[6]
            }
            for row in details
        ]

        # Рахуємо загальну суму
        total_price = sum(item['total_price'] for item in formatted_details)

        # Передаємо всі необхідні дані в шаблон
        return render_template('order_details.html',
                               token=token,
                               details=formatted_details,
                               total_price=total_price)

    except Exception as e:
        logging.error(f"Помилка завантаження деталей замовлення для order_id={order_id}: {e}", exc_info=True)
        flash("Помилка завантаження деталей замовлення.", "error")
        return redirect(url_for('orders', token=token))


@app.route('/<token>/admin/orders/<int:order_id>/update_status', methods=['POST'])
@requires_token_and_roles('admin')
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
@requires_token_and_roles('admin')
def admin_order_details(token, order_id):
    """
    Відображення деталей конкретного замовлення для адміна.
    """
    logging.info(f"Fetching details for order {order_id}")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Отримуємо основну інформацію про замовлення
        cursor.execute("""
            SELECT o.id, o.user_id, o.order_date, o.total_price, o.status,
                   u.username
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.id = %s
        """, (order_id,))
        order = cursor.fetchone()

        if not order:
            logging.warning(f"Order {order_id} not found")
            flash("Order not found", "error")
            return redirect(url_for('admin_orders', token=token))

        # Отримуємо деталі замовлення
        cursor.execute("""
            SELECT id, article, table_name, price, quantity, 
                   total_price, status, comment
            FROM order_details
            WHERE order_id = %s
        """, (order_id,))
        order_items = cursor.fetchall()

        logging.info(f"Found {len(order_items)} items for order {order_id}")

        return render_template(
            'admin_order_details.html',
            order=order,
            order_items=order_items,
            token=token
        )

    except Exception as e:
        logging.error(f"Error fetching order details: {e}", exc_info=True)
        flash("Failed to load order details", "error")
        return redirect(url_for('admin_orders', token=token))

    finally:
        cursor.close()
        conn.close()


@app.route('/<token>/admin/orders', methods=['GET'])
@requires_token_and_roles('admin')
def admin_orders(token):
    """
    Відображення всіх замовлень для адміністратора.
    """
    logging.info(f"Starting admin_orders route with token: {token}")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        logging.debug("Executing orders query...")
        cursor.execute("""
            SELECT 
                o.id, 
                o.order_date, 
                o.total_price, 
                o.status,
                u.username
            FROM orders o
            JOIN users u ON o.user_id = u.id
            ORDER BY o.order_date DESC;
        """)
        orders = cursor.fetchall()
        logging.info(f"Successfully fetched {len(orders)} orders")
        logging.debug(f"First order sample: {orders[0] if orders else 'No orders'}")

        return render_template('admin_orders.html', orders=orders, token=token)

    except Exception as e:
        logging.error(f"Error in admin_orders: {str(e)}", exc_info=True)
        flash("Failed to load orders.", "error")
        return redirect(url_for('admin_dashboard', token=token))

    finally:
        cursor.close()
        conn.close()
        logging.info("Database connection closed in admin_orders")


# Ролі користувачеві
@app.route('/<token>/admin/assign_roles', methods=['GET', 'POST'])
@requires_token_and_roles('admin')  # Вкажіть 'admin' або іншу роль
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
@requires_token_and_roles('admin')
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

            cache.delete_memoized(search_articles)
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


# маршрут для перегляду статистики в адмін-панелі
@app.route('/<token>/admin/cache-stats')
@requires_token_and_roles('admin')
def view_cache_stats(token):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SELECT * FROM cache_stats ORDER BY timestamp DESC LIMIT 100")
        stats = cursor.fetchall()
    return render_template('cache_stats.html', stats=stats, token=token)


# 
@app.route('/import_status', methods=['GET'])
def get_import_status():
    logging.info("get_import_status function called.")
    return jsonify(
        {"status": "success", "message": f"Uploaded {len(data)} rows to table '{table_name}' successfully."}), 200




@app.route('/<token>/admin/compare_prices', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
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
@requires_token_and_roles('user', 'user_25', 'user_29')
def upload_file(token):
    try:
        logging.debug(f"Upload File Called with token: {token}")
        # Очищення сесійних даних
        session['missing_articles'] = []
        session['items_without_table'] = []
        merged_articles = {}  # Словник для відстеження об'єднаних артикулів

        user_id = session.get('user_id')
        if not user_id:
            logging.error("User not authenticated.")
            flash("User not authenticated.", "error")
            return redirect(f'/{token}/')

        logging.info(f"User ID: {user_id} started file upload.")

        # Перевірка наявності файлу
        if 'file' not in request.files:
            logging.error("No file uploaded.")
            flash("No file uploaded.", "error")
            return redirect(f'/{token}/')

        file = request.files['file']
        logging.info(f"Uploaded file: {file.filename}")

        # Перевірка формату файлу
        if not file.filename.endswith('.xlsx'):
            logging.error("Invalid file format. Only .xlsx files are allowed.")
            flash("Invalid file format. Please upload an Excel file.", "error")
            return redirect(f'/{token}/')

        # Зчитування файлу
        try:
            df = pd.read_excel(file, header=None)
            logging.info(f"File read successfully. Shape: {df.shape}")
        except Exception as e:
            logging.error(f"Error reading Excel file: {e}", exc_info=True)
            flash("Error reading the file. Please check the format.", "error")
            return redirect(f'/{token}/')

        if df.shape[1] < 2:
            logging.error("Invalid file structure. Less than two columns found.")
            flash("Invalid file structure. Ensure the file has at least two columns.", "error")
            return redirect(f'/{token}/')

        # Заповнення відсутніх колонок
        for col in range(2, 4):
            if col >= df.shape[1]:
                df[col] = None

        logging.debug(f"Dataframe after preprocessing: {df.head()}")

        items_with_table = []
        items_without_table = []
        missing_articles = set()

        # Обробка даних з файлу
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT table_name FROM price_lists;")
            all_tables = [row[0] for row in cursor.fetchall()]
            logging.info(f"Fetched tables from price_lists: {all_tables}")

            for index, row in df.iterrows():
                try:
                    article = str(row[0]).strip() if pd.notna(row[0]) else None
                    quantity = int(row[1]) if pd.notna(row[1]) and str(row[1]).isdigit() else None
                    table_name = str(row[2]).strip() if pd.notna(row[2]) else None
                    comment = str(row[3]).strip() if pd.notna(row[3]) else None

                    if not article or not quantity:
                        logging.warning(f"Skipped invalid row at index {index}: {row.tolist()}")
                        continue

                    logging.debug(
                        f"Processing article: {article}, quantity: {quantity}, table: {table_name}, comment: {comment}")

                    if table_name:
                        if table_name not in all_tables:
                            logging.warning(f"Invalid table name '{table_name}' for article {article}.")
                            missing_articles.add(article)
                            continue

                        cursor.execute(f"SELECT price FROM {table_name} WHERE article = %s", (article,))
                        result = cursor.fetchone()

                        if result:
                            price = result[0]
                            items_with_table.append((article, price, table_name, quantity, comment))
                            logging.info(f"Article {article} found in {table_name} with price {price}.")
                        else:
                            missing_articles.add(article)
                            logging.warning(f"Article {article} not found in {table_name}. Skipping.")
                    else:
                        matching_tables = []
                        for table in all_tables:
                            cursor.execute(f"SELECT price FROM {table} WHERE article = %s", (article,))
                            if cursor.fetchone():
                                matching_tables.append(table)

                        if matching_tables:
                            if len(matching_tables) == 1:
                                cursor.execute(f"SELECT price FROM {matching_tables[0]} WHERE article = %s", (article,))
                                price = cursor.fetchone()[0]
                                items_with_table.append((article, price, matching_tables[0], quantity, comment))
                                logging.info(
                                    f"Article {article} automatically added from single table {matching_tables[0]}")
                            else:
                                logging.info(f"Article {article} found in multiple tables: {matching_tables}")
                                items_without_table.append((article, quantity, matching_tables, comment))
                        else:
                            missing_articles.add(article)
                            logging.warning(f"Article {article} not found in any table.")
                except Exception as e:
                    logging.error(f"Error processing row at index {index}: {row.tolist()} - {e}", exc_info=True)
                    continue

            logging.debug(f"Items with table: {items_with_table}")
            logging.debug(f"Items without table: {items_without_table}")
            logging.debug(f"Missing articles: {missing_articles}")

            # Додавання товарів з визначеними таблицями до кошика
            if items_with_table:
                for article, base_price, table_name, quantity, comment in items_with_table:
                    # Перевіряємо наявність в корзині перед додаванням
                    cursor.execute("""
                        SELECT quantity FROM cart 
                        WHERE user_id = %s AND article = %s AND table_name = %s
                    """, (user_id, article, table_name))
                    old_quantity = cursor.fetchone()

                    if old_quantity:
                        old_qty = old_quantity[0]
                        new_qty = old_qty + quantity
                        merged_articles[article] = [old_qty, new_qty]

                    role = session.get('role')
                    markup_percentage = get_markup_by_role(role)
                    final_price = calculate_price(base_price, markup_percentage)

                    cursor.execute("""
                        INSERT INTO cart (user_id, article, table_name, quantity, base_price, final_price, comment, added_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id, article, table_name) 
                        DO UPDATE SET 
                            quantity = cart.quantity + EXCLUDED.quantity,
                            final_price = EXCLUDED.final_price,
                            comment = EXCLUDED.comment
                    """, (user_id, article, table_name, quantity, base_price, final_price, comment))
                    logging.info(f"Article {article} added/updated in cart")

            conn.commit()

            # Збереження даних в сесії та обробка результатів
            session['items_without_table'] = items_without_table
            session['missing_articles'] = list(missing_articles)

            # Додаємо повідомлення про об'єднані артикули
            if merged_articles:
                merge_msg = "Merged articles: " + ", ".join(
                    f"{art} ({old} + {new-old} = {new})"
                    for art, (old, new) in merged_articles.items()
                )
                flash(merge_msg, "info")

            if items_without_table:
                flash(f"{len(items_without_table)} articles need table selection.", "warning")
                return redirect(url_for('intermediate_results', token=token))

            if missing_articles:
                flash(f"The following articles were not found: {', '.join(missing_articles)}", "warning")

            flash(f"File processed successfully. {len(items_with_table)} items added to cart.", "success")
            return redirect(url_for('cart', token=token))

    except Exception as e:
        logging.error(f"Error in upload_file: {e}", exc_info=True)
        flash("An error occurred during file upload. Please try again.", "error")
        return redirect(f'/{token}/')



@app.route('/<token>/intermediate_results', methods=['GET', 'POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def intermediate_results(token):
    """
    Обробляє статті без таблиці, надає можливість вибрати таблиці,
    а потім додає вибрані статті до кошика.
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
                                f"SELECT price FROM {selected_table} WHERE article = %s",
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

                            # Додавання товару в кошик
                            cursor.execute(
                                """
                                INSERT INTO cart (user_id, article, table_name, quantity, base_price, final_price, added_at, comment)
                                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                                ON CONFLICT (user_id, article, table_name) DO UPDATE SET
                                quantity = cart.quantity + EXCLUDED.quantity,
                                final_price = EXCLUDED.final_price,
                                comment = EXCLUDED.comment
                                """,
                                (user_id, article, selected_table, quantity, base_price, final_price, comment)
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
                            f"SELECT price FROM {table} WHERE article = %s",
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
@requires_token_and_roles('admin')
def utilities(token):
    return render_template('utilities.html', token=token)


@app.route('/<token>/admin/news', methods=['GET'])
@requires_token_and_roles('admin')
def admin_news(token):
    """
    Відображення списку всіх новин в адмін-панелі
    """
    logging.info(f"Accessing admin news with token: {token}")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""
            SELECT id, title, created_at, updated_at, is_published
            FROM news
            ORDER BY created_at DESC
        """)
        news_list = cursor.fetchall()
        logging.info(f"Fetched {len(news_list)} news items")
        
        return render_template('admin_news.html', news_list=news_list, token=token)
        
    except Exception as e:
        logging.error(f"Error fetching news: {e}")
        flash("Error loading news", "error")
        return redirect(url_for('admin_dashboard', token=token))
        
    finally:
        cursor.close()
        conn.close()


@app.route('/<token>/admin/news/create', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
def create_news(token):
    """
    Створення нової новини
    """
    if request.method == 'POST':
        logging.info("Processing news creation")
        try:
            title = request.form['title']
            content = request.form['content']
            html_content = request.form['html_content']
            is_published = bool(request.form.get('is_published'))
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO news (title, content, html_content, is_published)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (title, content, html_content, is_published))
            
            news_id = cursor.fetchone()[0]
            conn.commit()
            
            logging.info(f"Created news with id: {news_id}")
            flash("News created successfully!", "success")
            return redirect(url_for('admin_news', token=token))
            
        except Exception as e:
            logging.error(f"Error creating news: {e}")
            flash("Error creating news", "error")
            return redirect(url_for('create_news', token=token))
        finally:
            if 'conn' in locals():
                cursor.close()
                conn.close()
    
    return render_template('create_news.html', token=token)

@app.route('/<token>/news')
@requires_token_and_roles('user', 'user_25', 'user_29')
def user_news(token):
    """
    Відображення списку новин для користувачів
    """
    logging.info(f"Accessing user news with token: {token}")
    user_id = session.get('user_id')
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        # Отримуємо всі опубліковані новини та статус їх прочитання для користувача
        cursor.execute("""
            SELECT 
                n.id,
                n.title,
                n.content,
                n.created_at,
                CASE WHEN nr.id IS NOT NULL THEN true ELSE false END as is_read
            FROM news n
            LEFT JOIN news_reads nr ON nr.news_id = n.id AND nr.user_id = %s
            WHERE n.is_published = true
            ORDER BY n.created_at DESC
        """, (user_id,))
        
        news_list = cursor.fetchall()
        logging.info(f"Fetched {len(news_list)} news items for user {user_id}")
        
        return render_template('user_news.html', news_list=news_list, token=token)
        
    except Exception as e:
        logging.error(f"Error fetching news for user: {e}")
        flash("Error loading news", "error")
        return redirect(url_for('index', token=token))
        
    finally:
        cursor.close()
        conn.close()

@app.route('/<token>/news/<int:news_id>')
@requires_token_and_roles('user', 'user_25', 'user_29')
def get_news_details(token, news_id):
    """
    Отримання детальної інформації про новину
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""
            SELECT title, html_content, created_at
            FROM news
            WHERE id = %s AND is_published = true
        """, (news_id,))
        
        news = cursor.fetchone()
        if news:
            return jsonify({
                'title': news['title'],
                'html_content': news['html_content'],
                'created_at': news['created_at'].strftime('%d.%m.%Y %H:%M')
            })
        return jsonify({'error': 'News not found'}), 404
        
    except Exception as e:
        logging.error(f"Error fetching news details: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

def get_unread_news_count(user_id):
    """
    Підрахунок непрочитаних новин для користувача
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM news n
            LEFT JOIN news_reads nr ON nr.news_id = n.id AND nr.user_id = %s
            WHERE n.is_published = true AND nr.id IS NULL
        """, (user_id,))
        return cursor.fetchone()[0]
    finally:
        cursor.close()
        conn.close()

@app.context_processor
def inject_unread_news_count():
    if 'user_id' in session:
        return {'unread_news_count': get_unread_news_count(session['user_id'])}
    return {'unread_news_count': 0}


@app.route('/<token>/news/<int:news_id>/view', methods=['GET'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def view_news(token, news_id):
    """
    Тільки показує новину без зміни статусу
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cursor.execute("""
        SELECT title, html_content, created_at
        FROM news 
        WHERE id = %s
    """, (news_id,))
    news = cursor.fetchone()
    
    return render_template('view_news.html', news=news, token=token, news_id=news_id)

@app.route('/<token>/news/<int:news_id>/mark-read', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def mark_news_read(token, news_id):
    """
    Окремий endpoint для позначення новини як прочитаної
    """
    user_id = session.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO news_reads (user_id, news_id, read_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id, news_id) DO NOTHING
    """, (user_id, news_id))
    
    conn.commit()
    return jsonify({'success': True})

@app.route('/<token>/news/<int:news_id>/set-read', methods=['POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def set_news_as_read(token, news_id):
    """
    Endpoint for marking news as read
    """
    user_id = session.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO news_reads (user_id, news_id, read_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id, news_id) DO NOTHING
    """, (user_id, news_id))
    
    conn.commit()
    return jsonify({'success': True})


@app.route('/<token>/admin/news/<int:news_id>/edit', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
def edit_news(token, news_id):
    """
    Редагування існуючої новини
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        if request.method == 'POST':
            title = request.form['title']
            content = request.form['content']
            html_content = request.form['html_content']
            is_published = 'is_published' in request.form
            
            cursor.execute("""
                UPDATE news 
                SET title = %s, content = %s, html_content = %s, 
                    is_published = %s, updated_at = NOW()
                WHERE id = %s
            """, (title, content, html_content, is_published, news_id))
            
            conn.commit()
            flash("Новину успішно оновлено!", "success")
            return redirect(url_for('admin_news', token=token))
            
        cursor.execute("SELECT * FROM news WHERE id = %s", (news_id,))
        news = cursor.fetchone()
        
        if not news:
            flash("Новину не знайдено", "error")
            return redirect(url_for('admin_news', token=token))
            
        return render_template('edit_news.html', news=news, token=token)
        
    except Exception as e:
        logging.error(f"Помилка редагування новини: {e}")
        flash("Помилка оновлення новини", "error")
        return redirect(url_for('admin_news', token=token))
        
    finally:
        cursor.close()
        conn.close()


@app.route('/ping', methods=['GET'])
def ping():
    logging.info("ping function called.")  
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port)
