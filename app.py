from datetime import datetime
from decimal import Decimal
import time
import os
import logging
import bcrypt
from functools import wraps
import psycopg2
import psycopg2.extras
from flask import (
    Flask, render_template, request, session,
    redirect, url_for, flash, jsonify,
    send_file, get_flashed_messages, g
)
from flask_babel import Babel, gettext as _
from openpyxl import Workbook
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import random
import string

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('psycopg2')





# Налаштування логування
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

babel = Babel(app)

# Налаштування Babel
app.config['BABEL_DEFAULT_LOCALE'] = 'uk'
app.config['BABEL_SUPPORTED_LOCALES'] = ['uk', 'en', 'sk']

# Конфігурація доступних мов
LANGUAGES = {
    'uk': 'Українська',
    'en': 'English',
    'sk': 'Slovak'
}

def get_locale():
    return session.get('language', app.config['BABEL_DEFAULT_LOCALE'])

babel.init_app(app, locale_selector=get_locale)

# генерація коду для відстеження артикулів в документах
def generate_tracking_code():
    # Використовуємо великі літери та цифри
    chars = string.ascii_uppercase + string.digits
    # Генеруємо 8-значний код
    tracking_code = ''.join(random.choices(chars, k=8))
    return tracking_code

# генерація tracking_code в момент створення нового замовлення постачальнику
def create_supplier_order_details(order_id, article, quantity):
    conn = get_db_connection()
    cur = conn.cursor()

    tracking_code = generate_tracking_code()

    cur.execute("""
        INSERT INTO supplier_order_details 
        (supplier_order_id, article, quantity, tracking_code, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        RETURNING id
    """, (order_id, article, quantity, tracking_code))

    detail_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    conn.close()

    return detail_id


# Make LANGUAGES available to all templates
@app.context_processor
def inject_languages():
    return dict(LANGUAGES=LANGUAGES)

@app.route('/set_language/<language>')
def set_language(language):
    session['language'] = language
    return redirect(request.referrer or url_for('index'))

@app.before_request
def before_request():
    g.locale = session.get('language', 'uk')

# Додаємо фільтр для кольорів статусу замовлення
@app.template_filter('status_color')
def status_color(status):
    colors = {
        'new': 'primary',           # Нове замовлення
        'in_review': 'info',        # На розгляді менеджера
        'pending': 'warning',       # В очікуванні
        'accepted': 'success',      # Прийнято
        'cancelled': 'secondary',   # Скасовано
        'ordered_supplier': 'info',      # Замовлено у постачальника
        'invoice_received': 'primary',   # Отримано інвойс
        'in_transit': 'warning',         # В дорозі
        'ready_pickup': 'success',       # Готово до відвантаження
        'completed': 'success'           # Повністю виконано
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
        message_body = _("Thank you for your order!\n\nYour order details:\n")

        if ordered_items:
            message_body += _("Ordered items:\n")
            for item in ordered_items:
                message_body += _(
                    "- Article: {article}, "
                    "Price: {price:.2f}, "
                    "Quantity: {quantity}, "
                    "Comment: {comment}\n"
                ).format(
                    article=item['article'],
                    price=item['price'],
                    quantity=item['quantity'],
                    comment=item['comment'] or _('No comment')
                )

        if missing_articles:
            message_body += _("\nMissing articles:\n")
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


# Функція для визначення розділювача
def detect_delimiter(file_content):
    delimiters = [',', ';', '\t', ' ']
    sample_lines = file_content.splitlines()[:5]
    counts = {delimiter: 0 for delimiter in delimiters}

    for line in sample_lines:
        for delimiter in delimiters:
            counts[delimiter] += line.count(delimiter)

    return max(counts, key=counts.get)



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
        flash(_("Invalid token."), "error")
        return redirect(url_for('index'))  # Якщо токен недійсний, перенаправляємо на головну

    # Якщо токен валідний, зберігаємо роль і токен у сесії
    session['token'] = token
    session['role'] = role
    return render_template('user/index.html', role=role)

# Головна сторінка
@app.route('/')
def index():
    token = session.get('token')
    logging.debug(f"Session data in index: {dict(session)}")  # Логування стану сесії

    if not token:
        return render_template('user/search/simple_search.html')

    role = session.get('role')
    logging.debug(f"Role in index: {role}")  # Логування ролі користувача

    if role == "admin":
        return redirect(url_for('admin_dashboard', token=token))
    elif role == "user":
        return render_template('user/index.html', role=role)
    else:
        flash(_("Invalid token or role."), "error")
        return redirect(url_for('simple_search'))



# Пошук для користувачів без токену
@app.route('/simple_search', methods=['GET', 'POST'])
def simple_search():
    if request.method == 'POST':
        article = request.form.get('article', '').strip()
        if not article:
            flash(_("Please enter an article for search."), "error")
            return redirect(url_for('simple_search'))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT table_name FROM price_lists")
            tables = [row['table_name'] for row in cursor.fetchall()]

            results = []
            for table in tables:
                query = f"""
                    SELECT article, price, '{table}' AS table_name
                    FROM {table}
                    WHERE article = %s
                """
                cursor.execute(query, (article,))
                results.extend(cursor.fetchall())

            if results:
                logging.debug(f"Search results for article '{article}': {results}")
            else:
                logging.debug(f"No results found for article '{article}'.")

        except Exception as e:
            logging.error(f"Error in simple_search: {e}", exc_info=True)
            flash(_("An error occurred during the search. Please try again later."), "error")
            results = []

        finally:
            if 'conn' in locals() and conn:
                conn.close()

        return render_template('user/search/simple_search_results.html', results=results)

    return render_template('user/search/simple_search.html')


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
        return render_template('admin/admin_login.html', token=token)

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

        return render_template('admin/dashboard/admin_dashboard.html', users=users, token=token)
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

    return render_template('admin/users/create_user.html', roles=roles, token=token)


@app.route('/<token>/search', methods=['GET', 'POST'])
@requires_token_and_roles('user', 'user_25', 'user_29')
def search_articles(token):
    try:
        articles_input = request.form.get('articles', '').strip()
        if not articles_input:
            flash(_("Please enter at least one article."), "error")
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
                flash(_("Articles not found: {articles}").format(
                    articles=', '.join(missing_articles)), "warning")

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
                    'user/search/search_results.html',
                    grouped_results=multiple_prices,
                    missing_articles=missing_articles,
                    quantities=quantities,
                    comments=comments,
                    token=token
                )

            # Якщо всі артикули оброблені - перенаправляємо в кошик
            return redirect(url_for('cart', token=token))


    except Exception as e:
        logging.error(f"Error in search_articles: {e}", exc_info=True)
        flash(_("An error occurred while processing your request."), "error")
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
            'user/search/search_results.html',
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
            flash(_("You need to log in to view your cart."), "error")
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
            'user/cart/cart.html',
            cart_items=cart_items,
            total_price=total_price,
            missing_articles=missing_articles,
            token=token
        )

    except Exception as e:
        logging.error(f"Error in cart for user_id={user_id}: {str(e)}", exc_info=True)
        flash(_("Could not load your cart. Please try again."), "error")
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
            flash(_("User is not authenticated. Please log in."), "error")
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
        flash(_("Product added to cart!"), "success")
    except Exception as e:
        logging.error(f"Error in add_to_cart: {e}", exc_info=True)
        flash(_("Error adding product to cart."), "error")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            logging.debug("Database connection closed after adding to cart.")

    # Перенаправлення на сторінку результатів пошуку
    return render_template(
        'user/search/search_results.html',
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
            flash(_("Missing required information for removal"), "error")
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
                flash(_("Article {article} removed successfully").format(article=article), "success")
                logging.info(f"Article {article} removed from cart for user_id={user_id}")
            else:
                flash(_("Item not found in cart"), "warning")
                logging.warning(f"Failed to remove article {article} for user_id={user_id}")

    except Exception as e:
        logging.error(f"Error removing from cart: {e}", exc_info=True)
        flash(_("Error removing item from cart"), "error")

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
            flash(_("Invalid input: article or quantity missing."), "error")
            logging.error("Missing article or quantity in update_cart form.")
            return redirect(url_for('cart', token=token))

        quantity = int(quantity)

        if quantity < 1:
            flash(_("Quantity must be at least 1."), "error")
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
        flash(_("Cart updated successfully!"), "success")

    except Exception as e:
        logging.error(f"Error updating cart: {e}", exc_info=True)
        flash(_("Error updating cart."), "error")
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
        flash(_("Cart cleared successfully."), "success")

    except Exception as e:
        logging.error(f"Error clearing cart for user_id={user_id}: {e}", exc_info=True)
        flash(_("Error clearing cart."), "error")
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
            flash(_("User is not authenticated. Please log in."), "error")
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
            flash(_("Your cart is empty!"), "error")
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
        """, (user_id, total_price, "pending"))
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
                flash(_("Order placed, but we couldn't send a confirmation email."), "warning")

        # Очищаємо список відсутніх позицій
        session['missing_articles'] = []
        session.modified = True

        logging.info(f"Cart cleared and order placed successfully for user_id={user_id}")
        flash(_("Order placed successfully!"), "success")
        return redirect(request.referrer or url_for('cart'))

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Error placing order for user_id={user_id}: {str(e)}", exc_info=True)
        flash(_("Error placing order: {error}").format(error=str(e)), "error")
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
        flash(_("User is not authenticated."), "error")
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

        return render_template('user/orders/orders.html', orders=orders)

    except Exception as e:
        logging.error(f"Error fetching orders: {e}", exc_info=True)
        flash(_("Error fetching orders."), "error")
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

        # Отримуємо деталі замовлення та статус
        cursor.execute("""
            SELECT order_id, article, table_name, price, quantity, total_price, comment, status
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
                'comment': row[6] or _("No comment"),
                'status': row[7] or 'new'
            }
            for row in details
        ]

        # Рахуємо загальну суму
        total_price = sum(item['total_price'] for item in formatted_details)

        return render_template('user/orders/order_details.html',
                            token=token,
                            order_id=order_id,
                            details=formatted_details,
                            total_price=total_price)

    except Exception as e:
        logging.error(f"Помилка завантаження деталей замовлення для order_id={order_id}: {e}", exc_info=True)
        flash(_("Error loading order details."), "error")
        return redirect(url_for('orders', token=token))


@app.route('/<token>/admin/orders/<int:order_id>/update_status', methods=['POST'])
@requires_token_and_roles('admin')
def update_order_item_status(token, order_id):
    try:
        data = request.json
        if not data:
            logging.warning("No JSON data received.")
            return jsonify({"error": "Invalid JSON data."}), 400

        user_id = session.get('user_id')
        conn = get_db_connection()
        cursor = conn.cursor()

        logging.info(f"Received data for order {order_id}: {data}")

        valid_statuses = {
            'new', 'in_review', 'pending', 'accepted',
            'ordered_supplier', 'invoice_received', 'in_transit',
            'ready_pickup', 'completed', 'cancelled'
        }

        if not data.get('items'):
            logging.warning("No items found in request data.")
            return jsonify({"error": "No items provided."}), 400

        for item in data.get('items', []):
            detail_id = item.get('id')
            new_status = item.get('status')
            comment = item.get('comment', None)

            if not detail_id or not new_status:
                logging.warning(f"Missing required fields for item: {item}")
                continue

            if new_status not in valid_statuses:
                logging.warning(f"Invalid status provided: {new_status}")
                continue

            cursor.execute("SELECT status FROM order_details WHERE id = %s;", (detail_id,))
            current_status = cursor.fetchone()

            if current_status:
                current_status = current_status[0]
                logging.info(f"Updating item {detail_id}: {current_status} -> {new_status}")

                cursor.execute("""
                    UPDATE order_details
                    SET status = %s, comment = %s
                    WHERE id = %s;
                """, (new_status, comment, detail_id))

                cursor.execute("""
                    INSERT INTO order_changes (order_id, order_detail_id, field_changed, old_value, new_value, comment, changed_by)
                    VALUES (%s, %s, 'status', %s, %s, %s, %s);
                """, (order_id, detail_id, current_status, new_status, comment, user_id))

        conn.commit()

        # Оновлення статусу замовлення
        cursor.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE status = 'new') AS new_count,
                COUNT(*) FILTER (WHERE status = 'in_review') AS in_review_count,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                COUNT(*) FILTER (WHERE status = 'accepted') AS accepted_count,
                COUNT(*) FILTER (WHERE status = 'ordered_supplier') AS ordered_count,
                COUNT(*) FILTER (WHERE status = 'invoice_received') AS invoice_count,
                COUNT(*) FILTER (WHERE status = 'in_transit') AS transit_count,
                COUNT(*) FILTER (WHERE status = 'ready_pickup') AS ready_count,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                COUNT(*) AS total_count
            FROM order_details
            WHERE order_id = %s;
        """, (order_id,))
        counts = cursor.fetchone()

        if counts:
            total_items = counts[9]  # total_count

            # Визначення загального статусу замовлення
            if counts[8] == total_items:  # Всі completed
                new_order_status = 'completed'
            elif counts[7] > 0:  # Є ready_pickup
                new_order_status = 'ready_pickup'
            elif counts[6] > 0:  # Є in_transit
                new_order_status = 'in_transit'
            elif counts[5] > 0:  # Є invoice_received
                new_order_status = 'invoice_received'
            elif counts[4] > 0:  # Є ordered_supplier
                new_order_status = 'ordered_supplier'
            elif counts[3] > 0:  # Є accepted
                new_order_status = 'accepted'
            elif counts[2] > 0:  # Є pending
                new_order_status = 'pending'
            elif counts[1] > 0:  # Є in_review
                new_order_status = 'in_review'
            else:
                new_order_status = 'new'

            cursor.execute("UPDATE orders SET status = %s WHERE id = %s;", (new_order_status, order_id))
            conn.commit()
            logging.info(f"Order {order_id} status updated to {new_order_status}.")

        flash("Order and item statuses updated successfully.", "success")
        return jsonify({"message": "Statuses updated successfully."})

    except Exception as e:
        logging.error(f"Error in updating order items for order {order_id}: {e}")
        return jsonify({"error": "An error occurred while processing the request."}), 500
    finally:
        if conn:
            conn.close()
            logging.info(f"Database connection closed for order {order_id}.")


@app.route('/<token>/admin/orders/<int:order_id>', methods=['GET'])
@requires_token_and_roles('admin')
def admin_order_details(token, order_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Отримуємо інформацію про замовлення та користувача
        cursor.execute("""
            SELECT o.id, o.user_id, o.order_date, o.total_price, o.status,
                   u.username, u.email
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.id = %s
        """, (order_id,))
        order = cursor.fetchone()

        # Отримуємо деталі замовлення
        cursor.execute("""
            SELECT id, article, table_name, price, quantity, 
                   total_price, status, comment
            FROM order_details
            WHERE order_id = %s
            ORDER BY id
        """, (order_id,))
        order_items = cursor.fetchall()

        return render_template(
            'admin/orders/admin_order_details.html',
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
    Відображення всіх замовлень для адміністратора з фільтрацією по статусу.
    """
    logging.info(f"Starting admin_orders route with token: {token}")
    status_filter = request.args.get('status', '')
    logging.debug(f"Status filter: {status_filter}")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        base_query = """
            SELECT 
                o.id, 
                o.order_date, 
                o.total_price, 
                o.status,
                u.username
            FROM orders o
            JOIN users u ON o.user_id = u.id
        """

        params = []
        if status_filter:
            base_query += " WHERE o.status = %s"
            params.append(status_filter)

        base_query += " ORDER BY o.order_date DESC"

        logging.debug(f"Executing query: {base_query} with params: {params}")
        cursor.execute(base_query, params)
        orders = cursor.fetchall()

        logging.info(f"Successfully fetched {len(orders)} orders")
        logging.debug(f"First order sample: {orders[0] if orders else 'No orders'}")

        return render_template(
            'admin/orders/admin_orders.html',
            orders=orders,
            token=token,
            current_status=status_filter
        )

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
    return render_template('admin/users/assign_roles.html', user_roles=user_roles, users=users, roles=roles, token=token)







@app.route('/<token>/admin/supplier-mapping', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
def supplier_mapping(token):
    if request.method == 'POST':
        price_list_id = request.form.get('price_list_id')
        supplier_id = request.form.get('supplier_id')

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE price_lists 
                SET supplier_id = %s 
                WHERE id = %s
            """, (supplier_id, price_list_id))
            conn.commit()

        flash("Mapping updated successfully", "success")

    return redirect(url_for('manage_price_lists', token=token))

#
@app.route('/<token>/admin/manage-price-lists', methods=['GET'])
@requires_token_and_roles('admin')
def manage_price_lists(token):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cursor.execute("""
            SELECT 
                pl.id,
                pl.table_name,
                s.name as supplier_name,
                s.delivery_time,
                pl.created_at,
                s.id as supplier_id
            FROM price_lists pl
            LEFT JOIN suppliers s ON pl.supplier_id = s.id
            ORDER BY pl.created_at DESC
        """)
        price_lists = cursor.fetchall()

        # Отримуємо список всіх постачальників для випадаючого списку
        cursor.execute("SELECT id, name FROM suppliers ORDER BY name")
        suppliers = cursor.fetchall()

    return render_template('admin/price_lists/manage_price_lists.html',
                           price_lists=price_lists,
                           suppliers=suppliers,
                           token=token)


@app.route('/<token>/admin/update-price-list-supplier', methods=['POST'])
@requires_token_and_roles('admin')
def update_price_list_supplier(token):
    try:
        price_list_id = request.form.get('price_list_id')
        supplier_id = request.form.get('supplier_id')

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE price_lists
                SET supplier_id = %s
                WHERE id = %s
            """, (supplier_id, price_list_id))
            conn.commit()

        flash("Постачальника успішно оновлено", "success")

    except Exception as e:
        logging.error(f"Error updating supplier: {e}")
        flash("Помилка при оновленні постачальника", "error")

    return redirect(url_for('manage_price_lists', token=token))


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
            return render_template('admin/price_lists/upload_price_list.html', price_lists=price_lists, token=token)
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

# роут для керування постачальниками
@app.route('/<token>/admin/manage-suppliers', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
def manage_suppliers(token):
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            delivery_time = request.form.get('delivery_time')

            logging.info(f"Creating new supplier: {name}, delivery time: {delivery_time} days")

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO suppliers (name, delivery_time)
                    VALUES (%s, %s)
                    RETURNING id
                """, (name, delivery_time))
                supplier_id = cursor.fetchone()[0]
                conn.commit()

                logging.info(f"Created supplier with ID: {supplier_id}")
                flash(f"Постачальника {name} успішно створено", "success")
                return redirect(url_for('manage_suppliers', token=token))

        except Exception as e:
            logging.error(f"Error creating supplier: {e}")
            flash("Помилка при створенні постачальника", "error")

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("""
            SELECT id, name, delivery_time, created_at
            FROM suppliers 
            ORDER BY name
        """)
        suppliers = cursor.fetchall()

    return render_template('admin/suppliers/manage_suppliers.html',
                           suppliers=suppliers,
                           token=token)




# створення замовлення постачальнику
@app.route('/<token>/admin/supplier-orders/create', methods=['POST'])
@requires_token_and_roles('admin')
def create_supplier_order(token):
    try:
        supplier_id = request.form.get('supplier_id')
        order_number = f"SO-{supplier_id}-{datetime.now().strftime('%Y%m%d%H%M')}"

        conn = get_db_connection()
        cur = conn.cursor()

        # Створюємо нове замовлення постачальнику
        cur.execute("""
            INSERT INTO supplier_orders (supplier_id, order_number, status)
            VALUES (%s, %s, 'new')
            RETURNING id
        """, (supplier_id, order_number))

        supplier_order_id = cur.fetchone()[0]

        # Отримуємо деталі замовлення з order_details
        cur.execute("""
            SELECT id, article, quantity 
            FROM order_details 
            WHERE status = 'accepted' AND table_name IN (
                SELECT table_name 
                FROM price_lists 
                WHERE supplier_id = %s
            )
        """, (supplier_id,))

        details = cur.fetchall()

        # Додаємо деталі до замовлення постачальнику
        for detail in details:
            detail_id, article, quantity = detail
            tracking_code = generate_tracking_code()

            # Додаємо в supplier_order_details
            cur.execute("""
                INSERT INTO supplier_order_details 
                (supplier_order_id, article, quantity, tracking_code)
                VALUES (%s, %s, %s, %s)
            """, (supplier_order_id, article, quantity, tracking_code))

            # Оновлюємо статус в order_details на 'ordered'
            cur.execute("""
                UPDATE order_details 
                SET status = 'ordered_supplier'
                WHERE id = %s
            """, (detail_id,))

        # Оновлюємо статус замовлення на 'ordered_supplier'
        cur.execute("""
            UPDATE orders 
            SET status = 'ordered_supplier' 
            WHERE id IN (
                SELECT DISTINCT order_id 
                FROM order_details 
                WHERE status = 'ordered'
            )
        """)

        conn.commit()
        flash('Supplier order created successfully', 'success')

    except Exception as e:
        conn.rollback()
        logging.error(f"Помилка створення замовлення постачальнику: {e}")
        flash('Error creating supplier order', 'error')

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('list_supplier_orders', token=token))



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
            return render_template('user/search/compare_prices.html', price_lists=price_lists)
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
                'user/search/compare_prices_results.html',
                better_in_first=better_in_first,
                better_in_second=better_in_second,
                same_prices=same_prices
            )

        except Exception as e:
            logging.error(f"Error during POST request: {str(e)}", exc_info=True)
            flash("An error occurred during comparison.", "error")
            return redirect(request.referrer or url_for('compare_prices'))

# Маршрут для відображення форми (new_supplier_order):
@app.route('/<token>/admin/supplier-orders/new', methods=['GET'])
@requires_token_and_roles('admin')
def new_supplier_order(token):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT id, name FROM suppliers ORDER BY name")
    suppliers = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('admin/supplier_orders_create.html',
                           token=token,
                           suppliers=suppliers)


@app.route('/<token>/api/price-lists/<supplier_id>')
@requires_token_and_roles('admin')
def get_supplier_price_lists(token, supplier_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT id, table_name 
        FROM price_lists 
        WHERE supplier_id = %s
    """, (supplier_id,))

    price_lists = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({'price_lists': price_lists})

# сторінка перегляду замовлень постачальників
@app.route('/<token>/admin/supplier-orders', methods=['GET'])
@requires_token_and_roles('admin')
def list_supplier_orders(token):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Отримуємо всі замовлення з деталями
    cur.execute("""
        SELECT 
            so.id,
            so.order_number,
            so.created_at,
            so.status,
            s.name as supplier_name,
            COUNT(sod.id) as items_count,
            SUM(sod.quantity) as total_quantity
        FROM supplier_orders so
        JOIN suppliers s ON so.supplier_id = s.id
        LEFT JOIN supplier_order_details sod ON so.id = sod.supplier_order_id
        GROUP BY so.id, s.name
        ORDER BY so.created_at DESC
    """)

    orders = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('admin/supplier_orders_list.html',
                           token=token,
                           orders=orders)

# маршрут для перегляду деталей замовлення постачальнику
@app.route('/<token>/admin/supplier-orders/<order_id>', methods=['GET'])
@requires_token_and_roles('admin')
def view_supplier_order(token, order_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Отримуємо основну інформацію про замовлення
    cur.execute("""
        SELECT 
            so.*,
            s.name as supplier_name
        FROM supplier_orders so
        JOIN suppliers s ON so.supplier_id = s.id
        WHERE so.id = %s
    """, (order_id,))

    order = cur.fetchone()

    # Отримуємо деталі замовлення
    cur.execute("""
        SELECT *
        FROM supplier_order_details
        WHERE supplier_order_id = %s
        ORDER BY created_at
    """, (order_id,))

    details = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('admin/supplier_order_details.html',
                           token=token,
                           order=order,
                           details=details)

# Функція експорту в Excel замовлень постачальнику
@app.route('/<token>/admin/supplier-orders/<int:order_id>/export')
def export_supplier_order(token, order_id):
    logging.info(f"Starting export for supplier order {order_id}")

    if validate_token(token):
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # Get order info
            cur.execute("""
                SELECT 
                    so.id,
                    so.created_at,
                    so.status,
                    so.order_number,
                    s.name as supplier_name
                FROM supplier_orders so
                JOIN suppliers s ON so.supplier_id = s.id
                WHERE so.id = %s
            """, [order_id])
            order = cur.fetchone()

            if order:
                # Get order details with correct column names
                cur.execute("""
                    SELECT 
                        article,
                        quantity,
                        tracking_code,
                        created_at
                    FROM supplier_order_details
                    WHERE supplier_order_id = %s
                """, [order_id])
                items = cur.fetchall()

                workbook = Workbook()
                sheet = workbook.active

                # Headers
                sheet['A1'] = f'Supplier Order #{order["order_number"]}'
                sheet['A2'] = f'Supplier: {order["supplier_name"]}'
                sheet['A3'] = f'Status: {order["status"]}'
                sheet['A4'] = f'Created: {order["created_at"]}'

                # Column headers
                sheet['A6'] = 'Article'
                sheet['B6'] = 'Quantity'
                sheet['C6'] = 'Tracking Code'
                sheet['D6'] = 'Created At'

                row = 7
                for item in items:
                    sheet[f'A{row}'] = item['article']
                    sheet[f'B{row}'] = item['quantity']
                    sheet[f'C{row}'] = item['tracking_code']
                    sheet[f'D{row}'] = item['created_at']
                    row += 1

                output = BytesIO()
                workbook.save(output)
                output.seek(0)

                return send_file(
                    output,
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=True,
                    download_name=f'supplier_order_{order["order_number"]}.xlsx'
                )

        except Exception as e:
            logging.error(f"Export failed: {str(e)}")
            flash("Export failed. Please try again.", "error")
        finally:
            cur.close()
            conn.close()

    return redirect(url_for('list_supplier_orders', token=token))


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
    return render_template('admin/utilities.html', token=token)


@app.route('/<token>/admin/news', methods=['GET'])
@requires_token_and_roles('admin')
def admin_news(token):
    """
    Відображення списку всіх новин в адмін-панелі
    """
    logging.info(f"Доступ до адмін-новин з токеном: {token}")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Оновлений запит з вибіркою всіх мовних версій
        cursor.execute("""
            SELECT 
                id, 
                COALESCE(title_uk, title) as title_uk,
                COALESCE(title_en, title) as title_en,
                COALESCE(title_sk, title) as title_sk,
                created_at, 
                updated_at, 
                is_published
            FROM news
            ORDER BY created_at DESC
        """)
        news_list = cursor.fetchall()
        logging.info(f"Отримано {len(news_list)} новин")

        return render_template('admin/news/admin_news.html', news_list=news_list, token=token)

    except Exception as e:
        logging.error(f"Помилка отримання новин: {e}")
        flash("Помилка завантаження новин", "error")
        return redirect(url_for('admin_dashboard', token=token))

    finally:
        cursor.close()
        conn.close()


@app.route('/<token>/admin/news/create', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
def create_news(token):
    if request.method == 'POST':
        try:
            title_uk = request.form['title_uk']
            content_uk = request.form['content_uk']
            html_content_uk = request.form['html_content_uk']

            title_en = request.form['title_en']
            content_en = request.form['content_en']
            html_content_en = request.form['html_content_en']

            title_sk = request.form['title_sk']
            content_sk = request.form['content_sk']
            html_content_sk = request.form['html_content_sk']

            is_published = bool(request.form.get('is_published'))

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO news (
                    title_uk, content_uk, html_content_uk,
                    title_en, content_en, html_content_en,
                    title_sk, content_sk, html_content_sk,
                    is_published
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                title_uk, content_uk, html_content_uk,
                title_en, content_en, html_content_en,
                title_sk, content_sk, html_content_sk,
                is_published
            ))

            news_id = cursor.fetchone()[0]
            conn.commit()

            flash(_("News created successfully!"), "success")
            return redirect(url_for('admin_news', token=token))

        except Exception as e:
            logging.error(f"Error creating news: {e}")
            flash(_("Error creating news"), "error")
            return redirect(url_for('create_news', token=token))
        finally:
            if 'conn' in locals():
                cursor.close()
                conn.close()

    return render_template('admin/news/create_news.html', token=token)




@app.route('/<token>/admin/orders/<int:order_id>/accept-all', methods=['POST'])
@requires_token_and_roles('admin')
def accept_all_items(token, order_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Оновлюємо тільки статус, зберігаючи існуючі коментарі
        cursor.execute("""
            UPDATE order_details 
            SET status = 'accepted'
            WHERE order_id = %s
        """, (order_id,))

        # Оновлюємо статус замовлення
        cursor.execute("""
            UPDATE orders 
            SET status = 'accepted' 
            WHERE id = %s
        """, (order_id,))

        conn.commit()
        flash("All items accepted successfully", "success")

    except Exception as e:
        logging.error(f"Error accepting all items: {e}")
        flash("Error accepting items", "error")

    return redirect(url_for('admin_order_details', token=token, order_id=order_id))


@app.route('/<token>/admin/export-orders', methods=['GET'])
@requires_token_and_roles('admin')
def export_orders(token):
    try:
        wb = Workbook()

        # Create sheets for each supplier
        mercedes_sheet = wb.active
        mercedes_sheet.title = "Mercedes"
        bmw_sheet = wb.create_sheet("BMW")
        vag_sheet = wb.create_sheet("VAG")

        # Set headers for each sheet
        headers = ['Article', 'Total Quantity', 'Price List']
        for sheet in [mercedes_sheet, bmw_sheet, vag_sheet]:
            sheet.append(headers)

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            query = """
                SELECT 
                    od.article,
                    SUM(od.quantity) as total_quantity,
                    od.table_name,
                    CASE 
                        WHEN od.table_name LIKE '%mercedes%' THEN 'Mercedes'
                        WHEN od.table_name LIKE '%bmw%' THEN 'BMW'
                        WHEN od.table_name LIKE '%vag%' THEN 'VAG'
                        ELSE 'Unknown'
                    END as supplier
                FROM order_details od
                GROUP BY od.article, od.table_name
                ORDER BY od.article;
            """

            cursor.execute(query)
            results = cursor.fetchall()

            for row in results:
                data = [row['article'], row['total_quantity'], row['table_name']]
                if 'mercedes' in row['table_name'].lower():
                    mercedes_sheet.append(data)
                elif 'bmw' in row['table_name'].lower():
                    bmw_sheet.append(data)
                elif 'vag' in row['table_name'].lower():
                    vag_sheet.append(data)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='supplier_orders.xlsx'
        )

    except Exception as e:
        logging.error(f"Error exporting orders: {e}")
        flash("Error exporting orders", "error")
        return redirect(url_for('admin_dashboard', token=token))


@app.route('/api/update-supplier-statuses', methods=['POST'])
@requires_token_and_roles('admin')
def update_supplier_statuses():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        df = pd.read_excel(file)

        conn = get_db_connection()
        cursor = conn.cursor()

        for _, row in df.iterrows():
            cursor.execute("""
                UPDATE order_details 
                SET status = %s 
                WHERE article = %s AND order_id = %s
            """, (row['status'], row['article'], row['order_id']))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        logging.error(f"Error updating statuses: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/process-supplier-invoice', methods=['POST'])
@requires_token_and_roles('admin')
def process_supplier_invoice():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        df = pd.read_excel(file)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Створюємо новий інвойс
        cursor.execute("""
            INSERT INTO supplier_invoices (invoice_number, supplier_id, status)
            VALUES (%s, %s, 'received')
            RETURNING id
        """, (df['invoice_number'].iloc[0], df['supplier_id'].iloc[0]))

        invoice_id = cursor.fetchone()[0]

        # Додаємо зв'язки замовлень з інвойсом
        for _, row in df.iterrows():
            cursor.execute("""
                INSERT INTO order_invoice_links 
                (order_id, invoice_id, article, quantity, status)
                VALUES (%s, %s, %s, %s, 'in_transit')
            """, (row['order_id'], invoice_id, row['article'], row['quantity']))

            # Оновлюємо статус замовлення
            cursor.execute("""
                UPDATE order_details 
                SET status = 'in_transit' 
                WHERE article = %s AND order_id = %s
            """, (row['article'], row['order_id']))

        conn.commit()
        return jsonify({'success': True})

    except Exception as e:
        logging.error(f"Error processing invoice: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/<token>/news')
@requires_token_and_roles('user', 'user_25', 'user_29')
def user_news(token):
    """
    Відображення списку новин для користувачів з підтримкою багатомовності
    """
    logging.info(f"Accessing user news with token: {token}")
    user_id = session.get('user_id')
    current_lang = session.get('language', 'uk')

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        cursor.execute(f"""
            SELECT 
                n.id,
                n.title_{current_lang} as title,
                n.content_{current_lang} as content,
                n.html_content_{current_lang} as html_content,
                n.created_at,
                CASE WHEN nr.id IS NOT NULL THEN true ELSE false END as is_read
            FROM news n
            LEFT JOIN news_reads nr ON nr.news_id = n.id AND nr.user_id = %s
            WHERE n.is_published = true
            ORDER BY n.created_at DESC
        """, (user_id,))

        news_list = cursor.fetchall()
        logging.info(f"Fetched {len(news_list)} news items for user {user_id} in language {current_lang}")

        return render_template('user/news/user_news.html',
                               news_list=news_list,
                               token=token,
                               current_lang=current_lang)

    except Exception as e:
        logging.error(f"Error fetching news for user: {e}")
        flash(_("Error loading news"), "error")
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
        return jsonify({'error': _('News not found')}), 404

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
    Відображення окремої новини з підтримкою багатомовності
    """
    # Отримуємо поточну мову користувача, за замовчуванням українська
    current_lang = session.get('language', 'uk')

    # Підключаємося до бази даних
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Виконуємо запит з підтримкою старих та нових полів через COALESCE
        cursor.execute("""
            SELECT *, 
                COALESCE(title_uk, title) as title_uk,
                COALESCE(title_en, title) as title_en,
                COALESCE(title_sk, title) as title_sk,
                COALESCE(html_content_uk, html_content) as html_content_uk,
                COALESCE(html_content_en, html_content) as html_content_en,
                COALESCE(html_content_sk, html_content) as html_content_sk,
                created_at
            FROM news 
            WHERE id = %s
        """, (news_id,))

        news = cursor.fetchone()

        if not news:
            flash("Новину не знайдено", "error")
            return redirect(url_for('user_news', token=token))

        # Передаємо дані в шаблон
        return render_template('view_news.html',
                               news=news,
                               token=token,
                               news_id=news_id,
                               current_lang=current_lang)

    except Exception as e:
        logging.error(f"Помилка при відображенні новини {news_id}: {e}")
        flash("Помилка при завантаженні новини", "error")
        return redirect(url_for('user_news', token=token))

    finally:
        cursor.close()
        conn.close()


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
    Редагування багатомовної новини
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        if request.method == 'POST':
            # Отримуємо дані для кожної мови
            data = {
                'uk': {
                    'title': request.form['title_uk'],
                    'content': request.form['content_uk'],
                    'html_content': request.form['html_content_uk']
                },
                'en': {
                    'title': request.form['title_en'],
                    'content': request.form['content_en'],
                    'html_content': request.form['html_content_en']
                },
                'sk': {
                    'title': request.form['title_sk'],
                    'content': request.form['content_sk'],
                    'html_content': request.form['html_content_sk']
                }
            }

            is_published = 'is_published' in request.form

            cursor.execute("""
                UPDATE news 
                SET title_uk = %s, content_uk = %s, html_content_uk = %s,
                    title_en = %s, content_en = %s, html_content_en = %s,
                    title_sk = %s, content_sk = %s, html_content_sk = %s,
                    is_published = %s, updated_at = NOW()
                WHERE id = %s
            """, (
                data['uk']['title'], data['uk']['content'], data['uk']['html_content'],
                data['en']['title'], data['en']['content'], data['en']['html_content'],
                data['sk']['title'], data['sk']['content'], data['sk']['html_content'],
                is_published, news_id
            ))

            conn.commit()
            flash("Новину успішно оновлено!", "success")
            return redirect(url_for('admin_news', token=token))

        cursor.execute("SELECT * FROM news WHERE id = %s", (news_id,))
        news = cursor.fetchone()

        if not news:
            flash("Новину не знайдено", "error")
            return redirect(url_for('admin_news', token=token))

        return render_template('admin/news/edit_news.html', news=news, token=token)

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

