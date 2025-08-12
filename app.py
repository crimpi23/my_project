import csv
import io
import re
import time
import json
import logging
from flask_caching import Cache
from datetime import datetime
from decimal import Decimal
from datetime import datetime
import os
import bcrypt
from functools import wraps
import psycopg2
import psycopg2.extras
from flask import (
    Flask, render_template, request, session,
    redirect, url_for, flash, jsonify, render_template_string,
    send_file, get_flashed_messages, g, send_from_directory,
    make_response  
)
import jinja2
from flask_babel import Babel, gettext as _
# from flask_wtf import CSRFProtect
# from flask_wtf.csrf import generate_csrf
import sys
import urllib.parse
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename
from email.mime.base import MIMEBase
from email import encoders
import math
from flask_apscheduler import APScheduler
from functools import wraps
from logging.handlers import RotatingFileHandler
from psycopg2.pool import ThreadedConnectionPool
import atexit
from contextlib import contextmanager
from datetime import datetime, timedelta
from flask_caching import Cache
from datetime import datetime, timedelta  # додаємо timedelta до імпорту
from decimal import Decimal
import secrets
import ftplib
from werkzeug.utils import secure_filename
import uuid
import socket
import uuid
from dotenv import load_dotenv
from urllib.parse import urlencode



load_dotenv()
# Create Flask app first
app = Flask(__name__, static_folder='static', static_url_path='/static')




def get_locale():
    if 'user_id' in session:
        # Якщо користувач авторизований, беремо його мову з БД
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT preferred_language FROM users WHERE id = %s",
                    (session['user_id'],)
                )
                result = cursor.fetchone()
                if result and result[0]:
                    # Якщо мова користувача українська, змінюємо на словацьку
                    if result[0] == 'uk':
                        return 'sk'
                    return result[0]
        except Exception as e:
            logging.error(f"Error getting user language: {e}")
    
    # Якщо користувач не авторизований або виникла помилка,
    # використовуємо мову з сесії або стандартну
    language = session.get('language', app.config['BABEL_DEFAULT_LOCALE'])
    # Якщо мова українська, змінюємо на словацьку
    if language == 'uk':
        return 'sk'
    return language




# Configure Babel
app.config['BABEL_DEFAULT_LOCALE'] = 'sk'
app.config['BABEL_SUPPORTED_LOCALES'] = ['sk', 'en', 'pl']
# Set secret key for sessions and CSRF
# app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))






# Initialize extensions
# csrf = CSRFProtect(app)
babel = Babel(app)
babel.init_app(app, locale_selector=get_locale)
cache = Cache(app, config={
    'CACHE_TYPE': 'SimpleCache',  # Кеш в пам'яті
    'CACHE_DEFAULT_TIMEOUT': 600
})

# Налаштування планувальника
class Config:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = "UTC"

# Ініціалізація планувальника
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

try:
    if not scheduler.running:
        scheduler.start()
        logging.info("Scheduler started during app initialization")
except Exception as e:
    logging.error(f"Error starting scheduler: {e}")

def make_lang_cache_key():
    """Cache key that isolates per-language AND per-user cart state"""
    lang = session.get('language', app.config.get('BABEL_DEFAULT_LOCALE', 'sk'))
    user = session.get('user_id', 'guest')
    cart_count = session.get('cart_count', 0)
    q = request.query_string.decode(errors='ignore')
    return f"{lang}:{user}:{cart_count}:{request.path}?{q}"



# Додай цю функцію після функції make_lang_cache_key()

def clear_page_cache_for_user():
    """Очищає кеш поточної сторінки для користувача"""
    try:
        # Створюємо ключі кешу для всіх можливих мов поточної сторінки
        languages = app.config['BABEL_SUPPORTED_LOCALES']
        user = session.get('user_id', 'guest')
        cart_count = session.get('cart_count', 0)
        
        for lang in languages:
            cache_key = f"{lang}:{user}:{cart_count}:{request.path}"
            cache.delete(cache_key)
            
        logging.info(f"Cleared page cache for {request.path}")
    except Exception as e:
        logging.error(f"Error clearing page cache: {e}")


# Реєстрація функції закриття пулу при завершенні роботи
def close_db_pool():
    if 'db_pool' in globals() and db_pool:
        db_pool.closeall()
        logging.info("Database connection pool closed")
atexit.register(close_db_pool)


# Налаштування шляху для збереження sitemap файлів залежно від середовища
if os.environ.get('RENDER'):
    # На Render використовуємо тимчасовий каталог, який напевно є доступним
    SITEMAP_DIR = '/tmp/sitemaps'
else:
    # Локально використовуємо static/sitemaps
    SITEMAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'sitemaps')

os.makedirs(SITEMAP_DIR, exist_ok=True)
logging.info(f"Sitemap directory set to: {SITEMAP_DIR}")





@contextmanager
def safe_db_connection():
    """Безпечний контекстний менеджер для роботи з БД"""
    conn = None
    try:
        conn = get_db_connection()
        yield conn
    finally:
        if conn:
            try:
                if not conn.closed:
                    if 'db_pool' in globals() and db_pool:
                        try:
                            db_pool.putconn(conn)
                        except Exception as e:
                            logging.warning(f"Error returning connection to pool: {e}")
                            try:
                                conn.close()
                            except:
                                pass
                    else:
                        conn.close()
            except Exception as e:
                logging.error(f"Error closing connection: {e}")

# Створюємо директорію для зберігання sitemap файлів
SITEMAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'sitemaps')
os.makedirs(SITEMAP_DIR, exist_ok=True)

@app.before_request
def store_utm_params():
    """Зберігає UTM-параметри в сесії"""
    utm_params = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']
    for param in utm_params:
        if param in request.args:
            session[param] = request.args.get(param)



# Запит про токен / Перевірка токена / Декоратор для перевірки токена
def requires_token_and_roles(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Для статических файлов не проверяем токен
            if request.path.startswith('/static/'):
                return f(*args, **kwargs)
                
            token = request.view_args.get('token')
            # Перевіряємо, чи це публічний маршрут
            is_public_route = 'public' in request.path or not any(segment in request.path for segment in ['admin', 'dashboard'])
            
            if not token:
                return redirect(url_for('index'))

            if not validate_token(token):
                # Для публічних маршрутів тихе перенаправлення без повідомлення
                if is_public_route:
                    return redirect(url_for('index'))
                else:
                    # Для адмін-маршрутів показуємо помилку
                    flash(_("Invalid token."), "error")
                    return redirect(url_for('index'))

            session_role = session.get('role')
            if not session_role:
                flash(_("Please log in."), "error")
                return redirect(url_for('login'))

            role_name = session_role
            if allowed_roles and role_name not in allowed_roles:
                flash(_("You don't have permission to access this page."), "error")
                return redirect(url_for('index'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def initialize_scheduler():
    """Ініціалізує планувальник для продакшн"""
    try:
        # Перевіряємо чи планувальник вже запущений
        if not scheduler.running:
            scheduler.start()
            logging.info("Scheduler started in production")
            
            # Перевіряємо і додаємо завдання
            job_ids = [job.id for job in scheduler.get_jobs()]
            
            if 'generate_sitemap_daily' not in job_ids:
                scheduler.add_job(
                    generate_sitemap_daily,
                    'cron', 
                    hour=2, 
                    minute=0,
                    id='generate_sitemap_daily'
                )
                logging.info("Added daily sitemap job")
                
            if 'generate_sitemap_weekly' not in job_ids:
                scheduler.add_job(
                    generate_sitemap_weekly,
                    'cron', 
                    day_of_week='mon', 
                    hour=3, 
                    minute=0,
                    id='generate_sitemap_weekly'
                )
                logging.info("Added weekly sitemap job")
                
            if 'generate_sitemap_monthly' not in job_ids:
                scheduler.add_job(
                    generate_sitemap_monthly,
                    'cron', 
                    day=1, 
                    hour=4, 
                    minute=0,
                    id='generate_sitemap_monthly'
                )
                logging.info("Added monthly sitemap job")
                
            if 'generate_sitemaps_distributed' not in job_ids:
                scheduler.add_job(
                    generate_sitemaps_distributed,
                    'interval',
                    days=30,
                    id='generate_sitemaps_distributed'
                )
                logging.info("Added distributed sitemap job")
                
        else:
            logging.info("Scheduler is already running")
                
        return True
    except Exception as e:
        logging.error(f"Error initializing scheduler: {e}")
        return False

try:
    initialize_scheduler()
    logging.info("Scheduler initialized during app startup")
except Exception as e:
    logging.error(f"Error initializing scheduler during startup: {e}")

def init_scheduler():
    """Ініціалізує планувальник та додає всі заплановані завдання"""
    try:
        # Перевіряємо, чи планувальник уже запущено
        if not scheduler.running:
            scheduler.start()
            logging.info("Scheduler started successfully")
        else:
            logging.info("Scheduler is already running")
        
        # Перевіряємо наявність наших завдань
        job_ids = [job.id for job in scheduler.get_jobs()]
        
        # Додаємо завдання, якщо вони не існують
        if 'generate_sitemap_daily' not in job_ids:
            scheduler.add_job(
                generate_sitemap_daily,
                'cron', 
                hour=2, 
                minute=0,
                id='generate_sitemap_daily'
            )
        
        if 'generate_sitemap_weekly' not in job_ids:
            scheduler.add_job(
                generate_sitemap_weekly,
                'cron', 
                day_of_week='mon', 
                hour=3, 
                minute=0,
                id='generate_sitemap_weekly'
            )
        
        if 'generate_sitemap_monthly' not in job_ids:
            scheduler.add_job(
                generate_sitemap_monthly,
                'cron', 
                day=1, 
                hour=4, 
                minute=0,
                id='generate_sitemap_monthly'
            )
            
        logging.info("All scheduler jobs initialized")
    except Exception as e:
        logging.error(f"Error initializing scheduler: {e}", exc_info=True)


def generate_sitemap_index_file():
    """Генерує sitemap index і зберігає на диск"""
    try:
        logging.info("Starting generation of sitemap index file")
        
        host_base = "https://autogroup.sk"
        today = datetime.now().strftime("%Y-%m-%d")

        sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        sitemap_xml += '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        
        # Відстежуємо кількість доданих sitemap файлів
        total_sitemaps = 0
        
        # Додаємо посилання на статичні файли sitemap
        static_files = ['sitemap-static.xml', 'sitemap-categories.xml', 'sitemap-blog.xml', 'sitemap-images.xml']
        for static_file in static_files:
            if os.path.exists(os.path.join(SITEMAP_DIR, static_file)):
                sitemap_xml += f'  <sitemap>\n    <loc>{host_base}/{static_file}</loc>\n    <lastmod>{today}</lastmod>\n  </sitemap>\n'
                total_sitemaps += 1
        
        # Додаємо файли stock
        stock_files = [f for f in os.listdir(SITEMAP_DIR) if f.startswith('sitemap-stock-') and f.endswith('.xml')]
        for stock_file in sorted(stock_files):
            sitemap_xml += f'  <sitemap>\n    <loc>{host_base}/{stock_file}</loc>\n    <lastmod>{today}</lastmod>\n  </sitemap>\n'
            total_sitemaps += 1
        
        # Додаємо файли enriched
        enriched_files = [f for f in os.listdir(SITEMAP_DIR) if f.startswith('sitemap-enriched-') and f.endswith('.xml')]
        for enriched_file in sorted(enriched_files):
            sitemap_xml += f'  <sitemap>\n    <loc>{host_base}/{enriched_file}</loc>\n    <lastmod>{today}</lastmod>\n  </sitemap>\n'
            total_sitemaps += 1
        
        # Додаємо файли other
        other_files = [f for f in os.listdir(SITEMAP_DIR) if f.startswith('sitemap-other-') and f.endswith('.xml')]
        for other_file in sorted(other_files):
            sitemap_xml += f'  <sitemap>\n    <loc>{host_base}/{other_file}</loc>\n    <lastmod>{today}</lastmod>\n  </sitemap>\n'
            total_sitemaps += 1
        
        # Перевіряємо, чи є хоча б один sitemap, щоб уникнути порожнього індексу
        if total_sitemaps == 0:
            logging.warning("No sitemap files found, adding a dummy sitemap entry")
            sitemap_xml += f'  <sitemap>\n    <loc>{host_base}/sitemap-static.xml</loc>\n    <lastmod>{today}</lastmod>\n  </sitemap>\n'
        
        sitemap_xml += '</sitemapindex>'
        
        # Записуємо в файл sitemap-index.xml
        file_path = os.path.join(SITEMAP_DIR, 'sitemap-index.xml')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(sitemap_xml)
        
        # Також зберігаємо копію як sitemap.xml для сумісності
        file_path2 = os.path.join(SITEMAP_DIR, 'sitemap.xml')
        with open(file_path2, 'w', encoding='utf-8') as f:
            f.write(sitemap_xml)
            
        logging.info(f"Sitemap index generated successfully: {file_path} with {total_sitemaps} sitemaps")
        return True
        
    except Exception as e:
        logging.error(f"Error generating sitemap index file: {e}", exc_info=True)
        return False

def generate_sitemap_images_file():
    """Генерує sitemap для зображень і зберігає на диск"""
    try:
        logging.info("Starting generation of images sitemap file")
        
        host_base = get_base_url() or "https://autogroup.sk"
        
        # Переконуємося, що базовий URL не закінчується слешем
        if host_base.endswith('/'):
            host_base = host_base[:-1]
        
        with safe_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо поточну мову для назв товарів
            lang = 'sk'  # За замовчуванням використовуємо словацьку
            
            # Створюємо XML для карти сайту зображень
            sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
            sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            sitemap_xml += 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
            
            # Отримуємо всі унікальні артикули з зображеннями
            cursor.execute("""
                SELECT DISTINCT product_article 
                FROM product_images
                ORDER BY product_article
            """)
            
            articles = cursor.fetchall()
            logging.info(f"Found {len(articles)} unique articles with images")
            
            # Для кожного артикула додаємо URL та зображення
            for article_row in articles:
                article = article_row['product_article']
                
                # Генеруємо URL товару
                product_url = f"{host_base}/product/{article}"
                
                # Додаємо URL товару
                sitemap_xml += f'  <url>\n'
                sitemap_xml += f'    <loc>{product_url}</loc>\n'
                
                # Отримуємо всі зображення для цього артикула
                cursor.execute("""
                    SELECT image_url, is_main
                    FROM product_images
                    WHERE product_article = %s
                    ORDER BY is_main DESC, id ASC
                """, (article,))
                
                images = cursor.fetchall()
                has_valid_images = False
                
                # Додаємо всі зображення для цього URL
                for image in images:
                    image_url = image['image_url']
                    
                    # Перевіряємо, чи URL не порожній і є коректним
                    if not image_url:
                        continue
                        
                    # Перевіряємо, чи URL починається з http:// або https://
                    if not image_url.startswith(('http://', 'https://')):
                        # Якщо URL відносний, додаємо базову адресу
                        image_url = f"{host_base}/{image_url.lstrip('/')}"
                    
                    # Додаткова перевірка на заглушки типу "new_image_url"
                    if image_url == "new_image_url" or not '.' in image_url:
                        continue
                        
                    has_valid_images = True
                    
                    # Отримуємо інформацію про товар
                    if not 'product' in locals() or product is None:
                        cursor.execute(f"""
                            SELECT 
                                article,
                                name_{lang} as name,
                                description_{lang} as description
                            FROM products
                            WHERE article = %s
                        """, (article,))
                        product = cursor.fetchone()
                    
                    # Генеруємо заголовок та опис для зображення
                    image_title = ""
                    image_caption = ""
                    
                    if product:
                        image_title = product['name'] or article
                        image_caption = product['description'] or ""
                    else:
                        image_title = article
                    
                    # Обмежуємо довжину заголовка та опису
                    image_title = image_title[:100]
                    image_caption = image_caption[:200] if image_caption else ""
                    
                    # Кодуємо спеціальні символи з використанням xml.sax.saxutils.escape
                    import xml.sax.saxutils as saxutils
                    image_title = saxutils.escape(image_title)
                    image_caption = saxutils.escape(image_caption)
                    
                    # Додаємо інформацію про зображення
                    sitemap_xml += f'    <image:image>\n'
                    sitemap_xml += f'      <image:loc>{image_url}</image:loc>\n'
                    
                    if image_title:
                        sitemap_xml += f'      <image:title>{image_title}</image:title>\n'
                        
                    if image_caption:
                        sitemap_xml += f'      <image:caption>{image_caption}</image:caption>\n'
                        
                    sitemap_xml += f'    </image:image>\n'
                
                # Закриваємо тег URL тільки якщо є дійсні зображення
                if has_valid_images:
                    sitemap_xml += f'  </url>\n'
                else:
                    # Якщо нема дійсних зображень, видаляємо початок URL
                    sitemap_xml = sitemap_xml.rsplit(f'  <url>\n', 1)[0]
                    sitemap_xml = sitemap_xml.rsplit(f'    <loc>{product_url}</loc>\n', 1)[0]
            
            sitemap_xml += '</urlset>'
            
            # Записуємо у файл
            file_path = os.path.join(SITEMAP_DIR, 'sitemap-images.xml')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(sitemap_xml)  
                
            logging.info(f"Images sitemap generated successfully: {file_path}")
            
            # Також оновлюємо індексний файл, щоб включити новий sitemap файл
            generate_sitemap_index_file()
            
        return True
        
    except Exception as e:
        logging.error(f"Error generating images sitemap file: {e}", exc_info=True)
        return False


def generate_sitemap_static_file():
    """Генерує static sitemap з мовними префіксами"""
    try:
        host_base = "https://autogroup.sk"
        languages = ['sk', 'en', 'pl']
        
        sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        sitemap_xml += 'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        
        # Статичні сторінки
        static_pages = [
            '/',                    # Головна сторінка
            '/about', 
            '/contacts', 
            '/shipping-payment', 
            '/returns', 
            '/car-service',
            '/terms',
            '/privacy'
        ]
        
        # Додаємо кожну сторінку для кожної мови
        for page in static_pages:
            for lang in languages:
                # Формуємо URL з мовним префіксом
                if page == '/':
                    url = f"{host_base}/{lang}/"
                else:
                    url = f"{host_base}/{lang}{page}"
                
                sitemap_xml += f'  <url>\n'
                sitemap_xml += f'    <loc>{url}</loc>\n'
                
                # Додаємо hreflang посилання
                for alt_lang in languages:
                    if page == '/':
                        alt_url = f"{host_base}/{alt_lang}/"
                    else:
                        alt_url = f"{host_base}/{alt_lang}{page}"
                    sitemap_xml += f'    <xhtml:link rel="alternate" hreflang="{alt_lang}" href="{alt_url}" />\n'
                
                # Пріоритет та частота оновлення
                if page == '/':
                    sitemap_xml += f'    <changefreq>daily</changefreq>\n'
                    sitemap_xml += f'    <priority>1.0</priority>\n'
                else:
                    sitemap_xml += f'    <changefreq>monthly</changefreq>\n'
                    sitemap_xml += f'    <priority>0.8</priority>\n'
                
                sitemap_xml += '  </url>\n'
        
        sitemap_xml += '</urlset>'
        
        # Записуємо в файл
        with open(os.path.join(SITEMAP_DIR, 'sitemap-static.xml'), 'w', encoding='utf-8') as f:
            f.write(sitemap_xml)
            
        logging.info("Multilingual static sitemap generated successfully")
        return True
        
    except Exception as e:
        logging.error(f"Error generating multilingual static sitemap: {e}", exc_info=True)
        return False

def generate_sitemap_categories_file():
    """Генерує categories sitemap з мовними префіксами"""
    try:
        host_base = "https://autogroup.sk"
        languages = ['sk', 'en', 'pl']
        
        sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        sitemap_xml += 'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Отримуємо всі категорії з перекладами
        cursor.execute("""
            SELECT 
                c.slug,
                c.name_sk IS NOT NULL as has_sk,
                c.name_en IS NOT NULL as has_en,
                c.name_pl IS NOT NULL as has_pl
            FROM categories c 
            WHERE c.slug IS NOT NULL AND c.slug != ''
        """)
        categories = cursor.fetchall()
        
        # Додаємо URL-адреси категорій для кожної мови
        for category in categories:
            slug = category['slug']
            
            # Визначаємо для яких мов є переклади
            available_languages = []
            for lang in languages:
                if category[f'has_{lang}']:
                    available_languages.append(lang)
            
            # Якщо немає жодного перекладу, використовуємо словацьку за замовчуванням
            if not available_languages:
                available_languages = ['sk']
            
            # Додаємо URL для кожної доступної мови
            for lang in available_languages:
                sitemap_xml += f'  <url>\n'
                sitemap_xml += f'    <loc>{host_base}/{lang}/category/{slug}</loc>\n'
                
                # Додаємо hreflang посилання
                for alt_lang in available_languages:
                    sitemap_xml += f'    <xhtml:link rel="alternate" hreflang="{alt_lang}" href="{host_base}/{alt_lang}/category/{slug}" />\n'
                
                sitemap_xml += f'    <changefreq>weekly</changefreq>\n'
                sitemap_xml += f'    <priority>0.8</priority>\n'
                sitemap_xml += '  </url>\n'
        
        cursor.close()
        conn.close()
        
        sitemap_xml += '</urlset>'
        
        # Записуємо в файл
        with open(os.path.join(SITEMAP_DIR, 'sitemap-categories.xml'), 'w', encoding='utf-8') as f:
            f.write(sitemap_xml)
            
        logging.info("Multilingual categories sitemap generated successfully")
        return True
        
    except Exception as e:
        logging.error(f"Error generating multilingual categories sitemap: {e}", exc_info=True)
        return False

def generate_sitemap_stock_files():
    """Генерує stock sitemap файли з багатомовними URL"""
    try:
        logging.info("Starting generation of multilingual stock sitemap files")
        start_time = datetime.now()
        
        host_base = "https://autogroup.sk"
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Підтримувані мови
        languages = ['sk', 'en', 'pl']
        
        # Рахуємо загальну кількість товарів
        cursor.execute("SELECT COUNT(*) FROM stock WHERE quantity > 0")
        total_products = cursor.fetchone()[0]
        
        # Розраховуємо кількість файлів (з урахуванням мультимовності)
        products_per_sitemap = 3500  # Зменшуємо, бо тепер у 3 рази більше URL
        total_files = max(1, math.ceil(total_products / products_per_sitemap))
        
        for page in range(1, total_files + 1):
            offset = (page - 1) * products_per_sitemap
            
            sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
            sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            sitemap_xml += 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1" '
            sitemap_xml += 'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            
            # Отримуємо товари зі стоку з назвами для всіх мов
            cursor.execute(f"""
                SELECT 
                    s.article, 
                    s.quantity,
                    s.price,
                    b.name as brand_name,
                    b.id as brand_id,
                    p.name_sk as name_sk,
                    p.name_en as name_en,
                    p.name_pl as name_pl,
                    p.description_sk as description_sk,
                    p.description_en as description_en,
                    p.description_pl as description_pl,
                    array_agg(
                        pi.image_url 
                        ORDER BY pi.is_main DESC, pi.id ASC
                    ) FILTER (WHERE pi.image_url IS NOT NULL) as images
                FROM stock s
                LEFT JOIN brands b ON s.brand_id = b.id
                LEFT JOIN products p ON s.article = p.article
                LEFT JOIN product_images pi ON s.article = pi.product_article
                WHERE s.quantity > 0
                GROUP BY s.article, s.quantity, s.price, b.name, b.id, 
                         p.name_sk, p.name_en, p.name_pl,
                         p.description_sk, p.description_en, p.description_pl
                ORDER BY s.article
                LIMIT %s OFFSET %s
            """, (products_per_sitemap, offset))
            
            products = cursor.fetchall()
            
            # Додаємо URL-адреси товарів для кожної мови
            for product in products:
                article = product['article']
                brand_name = product['brand_name'] or "AutogroupEU"
                images = product['images'] or []
                
                # Створюємо URL для кожної мови
                for lang in languages:
                    # Отримуємо назву та опис для поточної мови
                    product_name = (product[f'name_{lang}'] or 
                                   product['name_sk'] or 
                                   product['name_en'] or 
                                   article)
                    product_description = (product[f'description_{lang}'] or 
                                         product['description_sk'] or 
                                         product['description_en'] or 
                                         f"Buy {product_name} at AutogroupEU")
                    
                    # Початок URL запису
                    sitemap_xml += f'  <url>\n'
                    # НОВИЙ ФОРМАТ URL з мовним префіксом
                    sitemap_xml += f'    <loc>{host_base}/{lang}/product/{article}</loc>\n'
                    
                    # Додаємо hreflang посилання на інші мовні версії
                    for alt_lang in languages:
                        sitemap_xml += f'    <xhtml:link rel="alternate" hreflang="{alt_lang}" href="{host_base}/{alt_lang}/product/{article}" />\n'
                    
                    sitemap_xml += f'    <changefreq>weekly</changefreq>\n'
                    sitemap_xml += f'    <priority>0.8</priority>\n'
                    
                    # Додаємо зображення (до 3 зображень на товар для кожної мови)
                    for image_url in images[:3]:
                        if image_url:
                            import html
                            image_title = html.escape(f"{product_name} - {brand_name}")
                            
                            sitemap_xml += f'    <image:image>\n'
                            sitemap_xml += f'      <image:loc>{image_url}</image:loc>\n'
                            sitemap_xml += f'      <image:title>{image_title}</image:title>\n'
                            if product_description:
                                image_caption = html.escape(product_description[:200])
                                sitemap_xml += f'      <image:caption>{image_caption}</image:caption>\n'
                            sitemap_xml += f'    </image:image>\n'
                    
                    sitemap_xml += '  </url>\n'
            
            sitemap_xml += '</urlset>'
            
            # Записуємо в файл
            file_path = os.path.join(SITEMAP_DIR, f'sitemap-stock-{page}.xml')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(sitemap_xml)
                
            logging.info(f"Multilingual stock sitemap page {page} generated with {len(products) * len(languages)} URLs")
        
        cursor.close()
        conn.close()
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logging.info(f"Completed generation of multilingual stock sitemap files in {duration:.2f} seconds")
        return True
        
    except Exception as e:
        logging.error(f"Error generating multilingual stock sitemap files: {e}", exc_info=True)
        return False

def generate_sitemap_enriched_files():
    """Генерує enriched sitemap файли з багатомовними URL"""
    try:
        logging.info("Starting generation of multilingual enriched sitemap files")
        start_time = datetime.now()
        
        host_base = "https://autogroup.sk"
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Підтримувані мови
        languages = ['sk', 'en', 'pl']
        
        # ВИКЛЮЧАЄМО aftermarket і juaguar + обмежуємо ціновий діапазон
        cursor.execute("SELECT table_name FROM price_lists WHERE table_name NOT IN ('stock', 'aftermarket', 'juaguar')")
        price_list_tables = [row[0] for row in cursor.fetchall()]
        logging.info(f"Found {len(price_list_tables)} price list tables: {price_list_tables}")
        
        # Якщо немає прайс-листів, створюємо один пустий файл
        if not price_list_tables:
            logging.info("No price lists found, creating empty enriched sitemap")
            sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
            sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            sitemap_xml += '</urlset>'
            
            file_path = os.path.join(SITEMAP_DIR, 'sitemap-enriched-1.xml')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(sitemap_xml)
            
            logging.info(f"Created empty enriched sitemap at {file_path}")
            return True
        
        # Формуємо динамічний SQL для запиту всіх товарів з прайс-листів з ЦІНОВИМ ФІЛЬТРОМ
        union_queries = []
        for table in price_list_tables:
            union_queries.append(f"SELECT article, '{table}' AS source_table FROM {table} WHERE price BETWEEN 100 AND 800")
        
        all_price_list_query = " UNION ALL ".join(union_queries)
        
        # Рахуємо загальну кількість enriched товарів
        enriched_count_query = f"""
            SELECT COUNT(DISTINCT pl.article) 
            FROM ({all_price_list_query}) pl
            JOIN (
                SELECT p.article FROM products p
                UNION
                SELECT pi.product_article FROM product_images pi
            ) AS enriched ON pl.article = enriched.article
            LEFT JOIN stock s ON pl.article = s.article
            WHERE s.article IS NULL
        """
        
        cursor.execute(enriched_count_query)
        total_enriched = cursor.fetchone()[0]
        logging.info(f"Found {total_enriched} enriched products in price range 100-800€")

        # Розраховуємо кількість файлів (з урахуванням мультимовності)
        products_per_sitemap = 3500  # Зменшуємо, бо тепер у 3 рази більше URL
        total_files = max(1, math.ceil(total_enriched / products_per_sitemap))
        
        # Для кожного файлу створюємо окремий sitemap
        for page in range(1, total_files + 1):
            offset = (page - 1) * products_per_sitemap
            
            # Створюємо XML-заголовок з hreflang підтримкою
            sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
            sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            sitemap_xml += 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1" '
            sitemap_xml += 'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            
            # Запит для отримання товарів з описами або зображеннями + назвами мовами
            enriched_query = f"""
                SELECT DISTINCT 
                    pl.article, 
                    pl.source_table,
                    p.name_sk,
                    p.name_en, 
                    p.name_pl,
                    array_agg(DISTINCT pi.image_url) FILTER (WHERE pi.image_url IS NOT NULL) as images
                FROM ({all_price_list_query}) pl
                JOIN (
                    SELECT p.article FROM products p
                    UNION
                    SELECT pi.product_article FROM product_images pi
                ) AS enriched ON pl.article = enriched.article
                LEFT JOIN stock s ON pl.article = s.article
                LEFT JOIN products p ON pl.article = p.article
                LEFT JOIN product_images pi ON pl.article = pi.product_article
                WHERE s.article IS NULL
                GROUP BY pl.article, pl.source_table, p.name_sk, p.name_en, p.name_pl
                ORDER BY pl.article
                LIMIT {products_per_sitemap} OFFSET {offset}
            """
            
            cursor.execute(enriched_query)
            enriched_products = cursor.fetchall()
            
            # Додаємо URL для кожної мови для кожного товару
            for product in enriched_products:
                article = product['article']
                images = product['images'] or []
                
                # Створюємо URL для кожної мови
                for lang in languages:
                    # Отримуємо назву для поточної мови
                    product_name = (product[f'name_{lang}'] or 
                                   product['name_sk'] or 
                                   product['name_en'] or 
                                   article)
                    
                    sitemap_xml += f'  <url>\n'
                    # НОВИЙ ФОРМАТ URL з мовним префіксом
                    sitemap_xml += f'    <loc>{host_base}/{lang}/product/{article}</loc>\n'
                    
                    # Додаємо hreflang посилання на інші мовні версії
                    for alt_lang in languages:
                        sitemap_xml += f'    <xhtml:link rel="alternate" hreflang="{alt_lang}" href="{host_base}/{alt_lang}/product/{article}" />\n'
                    
                    sitemap_xml += f'    <changefreq>weekly</changefreq>\n'
                    sitemap_xml += f'    <priority>0.7</priority>\n'
                    
                    # Додаємо зображення, якщо вони є
                    for image_url in images[:3]:
                        if image_url:
                            import html
                            image_title = html.escape(f"{product_name}")
                            
                            sitemap_xml += f'    <image:image>\n'
                            sitemap_xml += f'      <image:loc>{image_url}</image:loc>\n'
                            sitemap_xml += f'      <image:title>{image_title}</image:title>\n'
                            sitemap_xml += f'    </image:image>\n'
                    
                    sitemap_xml += f'  </url>\n'
            
            # Закриваємо XML
            sitemap_xml += '</urlset>'
            
            # Записуємо в файл
            file_path = os.path.join(SITEMAP_DIR, f'sitemap-enriched-{page}.xml')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(sitemap_xml)
            
            logging.info(f"Generated multilingual sitemap-enriched-{page}.xml with {len(enriched_products) * len(languages)} URLs")
        
        cursor.close()
        conn.close()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logging.info(f"Completed generation of multilingual enriched sitemap files in {duration:.2f} seconds")
        return True
        
    except Exception as e:
        logging.error(f"Error generating multilingual enriched sitemap files: {e}", exc_info=True)
        return False

def generate_sitemap_other_files():
    """Генерує other sitemap файли і зберігає на диск з покращеною обробкою великих даних"""
    try:
        logging.info("Starting generation of other sitemap files")
        start_time = datetime.now()
        
        host_base = get_base_url() or "https://autogroup.sk"
        conn = None
        
        try:
            # Створюємо окреме з'єднання для початкового аналізу
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Отримання всіх таблиць прайс-листів
            cursor.execute("SELECT table_name FROM price_lists WHERE table_name != 'stock'")
            price_list_tables = [row[0] for row in cursor.fetchall()]
            logging.info(f"Found {len(price_list_tables)} price list tables: {price_list_tables}")
            
            # Якщо немає прайс-листів, створюємо один пустий файл
            if not price_list_tables:
                logging.info("No price lists found, creating empty other sitemap")
                sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
                sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                sitemap_xml += '</urlset>'
                
                file_path = os.path.join(SITEMAP_DIR, 'sitemap-other-1.xml')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(sitemap_xml)
                
                logging.info(f"Created empty other sitemap at {file_path}")
                cursor.close()
                conn.close()
                return True
                
            # Тепер реалізуємо покращену логіку обробки даних
            # Максимальна кількість URL в одному файлі
            MAX_URLS_PER_FILE = 10000
            
            # Лічильники для відстеження прогресу
            total_processed = 0
            file_num = 1
            
            # Буфер для накопичення URL перед записом у файл
            url_buffer = []
            
            # Для кожної таблиці
            for table_idx, table in enumerate(price_list_tables):
                table_start_time = datetime.now()
                logging.info(f"Processing table {table_idx+1}/{len(price_list_tables)}: {table}")
                
                # Створюємо новий курсор для кожної таблиці
                table_conn = get_db_connection()
                table_cursor = table_conn.cursor()
                
                # Рахуємо кількість товарів в таблиці для логування
                try:
                    table_cursor.execute(f"""
                        SELECT COUNT(*) FROM {table} t
                        LEFT JOIN (
                            SELECT p.article FROM products p
                            UNION
                            SELECT pi.product_article FROM product_images pi
                        ) AS enriched ON t.article = enriched.article
                        LEFT JOIN stock s ON t.article = s.article
                        WHERE s.article IS NULL AND enriched.article IS NULL
                    """)
                    table_count = table_cursor.fetchone()[0]
                    logging.info(f"Table {table} has {table_count} eligible products")
                except Exception as count_error:
                    logging.warning(f"Couldn't count records in {table}: {count_error}")
                    table_count = "unknown"
                finally:
                    table_cursor.close()
                    table_conn.close()
                
                # Будемо обробляти по BATCH_SIZE записів за раз
                BATCH_SIZE = 10000
                offset = 0
                
                while True:
                    # Нове з'єднання для кожного пакету даних
                    batch_conn = get_db_connection()
                    batch_cursor = batch_conn.cursor()
                    
                    # Встановлюємо timeout для запиту
                    batch_cursor.execute("SET statement_timeout = 60000") # 60 секунд
                    
                    # Запит для отримання пакету товарів
                    query = f"""
                        SELECT DISTINCT t.article 
                        FROM {table} t
                        LEFT JOIN (
                            SELECT p.article FROM products p
                            UNION
                            SELECT pi.product_article FROM product_images pi
                        ) AS enriched ON t.article = enriched.article
                        LEFT JOIN stock s ON t.article = s.article
                        WHERE s.article IS NULL AND enriched.article IS NULL
                        ORDER BY t.article
                        LIMIT {BATCH_SIZE} OFFSET {offset}
                    """
                    
                    try:
                        batch_cursor.execute(query)
                        batch_products = batch_cursor.fetchall()
                        
                        # Якщо немає даних у цьому пакеті, переходимо до наступної таблиці
                        if not batch_products:
                            batch_cursor.close()
                            batch_conn.close()
                            logging.info(f"Finished processing table {table}, processed {offset} records")
                            break
                            
                        # Додаємо URL для кожного товару в пакеті до буфера
                        for product in batch_products:
                            article = product[0]
                            url_buffer.append(f"""  <url>
    <loc>{host_base}/product/{article}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>""")
                            
                        # Якщо буфер досяг або перевищив ліміт, записуємо файл
                        while len(url_buffer) >= MAX_URLS_PER_FILE:
                            # Вилучаємо перші MAX_URLS_PER_FILE елементів з буфера
                            current_urls = url_buffer[:MAX_URLS_PER_FILE]
                            url_buffer = url_buffer[MAX_URLS_PER_FILE:]
                            
                            # Створюємо і записуємо файл
                            sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
                            sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                            sitemap_xml += '\n'.join(current_urls)
                            sitemap_xml += '\n</urlset>'
                            
                            file_path = os.path.join(SITEMAP_DIR, f'sitemap-other-{file_num}.xml')
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(sitemap_xml)
                            
                            total_processed += len(current_urls)
                            logging.info(f"Generated sitemap-other-{file_num}.xml with {len(current_urls)} URLs. Total: {total_processed}")
                            file_num += 1
                        
                        offset += len(batch_products)
                        
                    except Exception as batch_error:
                        logging.error(f"Error processing batch from {table} at offset {offset}: {batch_error}")
                        # Продовжуємо з наступним пакетом
                    finally:
                        batch_cursor.close()
                        batch_conn.close()
            
            # Після обробки всіх таблиць, записуємо залишок буфера
            if url_buffer:
                sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
                sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                sitemap_xml += '\n'.join(url_buffer)
                sitemap_xml += '\n</urlset>'
                
                file_path = os.path.join(SITEMAP_DIR, f'sitemap-other-{file_num}.xml')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(sitemap_xml)
                
                total_processed += len(url_buffer)
                logging.info(f"Generated sitemap-other-{file_num}.xml with {len(url_buffer)} URLs. Total: {total_processed}")
                file_num += 1
            
            # Загальна кількість згенерованих файлів
            total_files = file_num - 1
            
            # Видаляємо старі порожні файли, якщо вони існують
            for i in range(total_files + 1, 81):
                empty_path = os.path.join(SITEMAP_DIR, f'sitemap-other-{i}.xml')
                if os.path.exists(empty_path):
                    try:
                        os.remove(empty_path)
                        logging.info(f"Removed old empty file: sitemap-other-{i}.xml")
                    except Exception as e:
                        logging.warning(f"Could not remove file sitemap-other-{i}.xml: {e}")
            
            # Оновлюємо індексний файл
            generate_sitemap_index_file()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logging.info(f"Completed generation of {total_files} other sitemap files with {total_processed} URLs in {duration:.2f} seconds")
            return True
            
        finally:
            # Закриваємо з'єднання, якщо воно досі відкрите
            if conn:
                try:
                    if 'cursor' in locals() and cursor:
                        cursor.close()
                    conn.close()
                except:
                    pass
            
    except Exception as e:
        logging.error(f"Error generating other sitemap files: {e}", exc_info=True)
        return False


def generate_priority_sitemap():
    """Генерує sitemap для пріоритетних товарів"""
    try:
        logging.info("Starting priority sitemap generation")
        
        host_base = "https://autogroup.sk"
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        
        # Головна сторінка
        sitemap_xml += f'  <url>\n    <loc>{host_base}/</loc>\n    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>\n'
        
        # Додаємо топ продукти зі складу з високим пріоритетом
        cursor.execute("""
            SELECT s.article 
            FROM stock s 
            WHERE quantity > 5
            ORDER BY price DESC 
            LIMIT 1000
        """)
        
        top_products = cursor.fetchall()
        for product in top_products:
            sitemap_xml += f'  <url>\n    <loc>{host_base}/product/{product["article"]}</loc>\n    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>\n'
        
        sitemap_xml += '</urlset>'
        
        # Записуємо у файл
        file_path = os.path.join(SITEMAP_DIR, 'sitemap-priority.xml')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(sitemap_xml)
        
        logging.info(f"Generated priority sitemap with {len(top_products) + 1} URLs")
        
        # Додаємо у індекс
        generate_sitemap_index_file()
        
        logging.info("Priority sitemap generation completed successfully")
        return True
    except Exception as e:
        logging.error(f"Error generating priority sitemap: {e}", exc_info=True)
        return False

#функція нормалізації артикула при пошуку
def normalize_article(article):
    """
    Нормалізує артикул, видаляючи пробіли, дефіси та крапки
    """
    if not article:
        return ""
    
    # Видаляємо пробіли, дефіси та крапки і переводимо у верхній регістр
    normalized = article.replace(" ", "").replace("-", "").replace(".", "")
    return normalized.upper()

@scheduler.task('interval', id='generate_sitemaps_distributed', days=30)
def generate_sitemaps_distributed():
    """Розподілений генератор sitemap файлів"""
    try:
        logging.info("Starting distributed generation of all sitemap files")
        
        # Поступово генеруємо кожен тип sitemap з паузами
        generate_sitemap_static_file()
        time.sleep(10)  # Пауза між задачами
        
        generate_sitemap_categories_file()
        time.sleep(10)
        
        generate_sitemap_stock_files()
        time.sleep(30)  # Довша пауза після важкої операції
        
        generate_sitemap_enriched_files()
        time.sleep(30)
        
        generate_sitemap_other_files()
        time.sleep(30)
        
        generate_sitemap_index_file()
        
        logging.info("All sitemap files generated successfully via distributed task")
    except Exception as e:
        logging.error(f"Error in distributed sitemap generation: {e}", exc_info=True)

def generate_all_sitemaps():
    """Генерує всі файли sitemaps (БЕЗ other)"""
    try:
        logging.info("Starting generation of sitemap files (without other)")
        
        generate_sitemap_static_file()
        generate_sitemap_categories_file()
        generate_sitemap_stock_files()
        generate_sitemap_enriched_files()  # Тільки з описами/фото
        # generate_sitemap_other_files()  # ПОВНІСТЮ ВИКЛЮЧЕНО
        generate_sitemap_images_file()
        generate_sitemap_blog_file()  # Якщо є блог
        generate_sitemap_index_file()
        
        logging.info("Sitemap files generated successfully (without other)")
        return True
    except Exception as e:
        logging.error(f"Error generating sitemap files: {e}", exc_info=True)
        return False


# Додавання дампера для закриття невикористаних з'єднань
@scheduler.task('interval', id='check_pool_connections', minutes=5)
def check_pool_connections():
    """Періодична перевірка та закриття незайнятих з'єднань"""
    try:
        if 'db_pool' in globals() and db_pool:
            # Закриття всіх незайнятих з'єднань
            db_pool._pool.clear()
            logging.info("Cleared idle connections from pool")
    except Exception as e:
        logging.error(f"Error cleaning connection pool: {e}")


def get_base_url():
    """Get the base URL for the current request"""
    host = request.host_url.rstrip('/')
    
    # Завжди використовувати HTTPS для autogroup.sk
    if 'autogroup.sk' in host:
        return 'https://autogroup.sk'
    
    # Для локальної розробки використовуємо поточний URL
    return host




@app.context_processor
def utility_processor():
    def now():
        return datetime.now()
    
    return {
        'now': now,
        'timedelta': timedelta,  # Додаємо timedelta до контексту
        'get_base_url': get_base_url
        # Інші функції за потреби
    }

# налаштування для збереження файлів
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # Обмеження розміру файлу до 64MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Configure logging with rotation
if os.environ.get('FLASK_ENV') == 'production':
    # Продакшн - менше логів
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
else:
    # Розробка - детальні логи
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler('app.log', maxBytes=1024*1024, backupCount=5, encoding='utf-8')
        ]
    )




# Configure languages
LANGUAGES = {
    'sk': 'Slovenský',
    'en': 'English',
    'pl': 'Polski'
}

#    # Конфігурація доступних мов
# LANGUAGES = {
#    'uk': 'Українська',
#    'en': 'English',
#    'sk': 'Slovenský',
#    'pl': 'Polski'
#}



def add_noindex_header(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = f(*args, **kwargs)
        # Перевіряємо, чи є 'token' в аргументах функції
        if 'token' in kwargs:
            # Перевіряємо, чи response - це об'єкт Flask Response або має атрибут headers
            if hasattr(response, 'headers'):
                # Додаємо заголовок X-Robots-Tag
                response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            # Якщо це рядок або інший тип, конвертуємо його в Response
            elif isinstance(response, str):
                from flask import make_response
                response = make_response(response)
                response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response
    return decorated_function



@app.after_request
def add_noindex_headers_for_token_pages(response):
    """Додає заголовок X-Robots-Tag до всіх сторінок з токенами в URL"""
    # Перевіряємо чи URL містить гексадецимальний токен (32+ символи)
    if re.search(r'/[0-9a-f]{32,}/', request.path, re.IGNORECASE):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response

@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/product/') and not request.args.get('refresh'):
        response.headers['Cache-Control'] = 'public, max-age=3600'  # 1 година
    return response

@app.after_request
def add_more_cache_headers(response):
    if (request.path.startswith('/product/') or 
        request.path.startswith('/category/')) and not request.args.get('refresh'):
        response.headers['Cache-Control'] = 'public, max-age=3600, stale-while-revalidate=600'
        response.headers['Vary'] = 'Cookie, Accept-Language'
    return response

@app.route('/robots.txt')
def robots():
    robots_content = """User-agent: *
Crawl-delay: 10

# Дозволяємо основні сторінки
Allow: /
Allow: /product/
Allow: /category/
Allow: /blog/

# Дозволяємо тільки якісні sitemap
Allow: /sitemap-static.xml
Allow: /sitemap-categories.xml
Allow: /sitemap-stock-*
Allow: /sitemap-enriched-*
Allow: /sitemap-images.xml
Allow: /sitemap-blog.xml

# Блокуємо прайс-листи без описів
Disallow: /sitemap-other-*

# Блокуємо адмінку
Disallow: /admin/
Disallow: /*token*/
Disallow: /debug_*
Disallow: /api/

# Основний sitemap
Sitemap: https://autogroup.sk/sitemap-index.xml
"""
    response = make_response(robots_content)
    response.headers["Content-Type"] = "text/plain"
    return response



# Додайте на початку файлу або в підходящому місці
@app.before_request
def log_request_info():
    if request.path.startswith('/public_cart') or request.path.startswith('/public_remove_from_cart'):
        logging.info(f"Request: {request.path}, Method: {request.method}")
        logging.info(f"Form data: {dict(request.form)}")
        logging.info(f"Session user_id: {session.get('user_id')}")
        logging.info(f"Session cart_count: {session.get('cart_count')}")


# Функція валідації телефону
def validate_phone(phone_number):
    """Basic phone number validation"""
    try:
        # Видаляємо всі пробіли з номера
        phone = phone_number.strip().replace(' ', '')
        
        # Перевіряємо базовий формат
        if not phone:
            return False, "Phone number is required"
            
        # Перевіряємо наявність '+' на початку
        if not phone.startswith('+'):
            return False, "Phone number must start with +"
            
        # Перевіряємо що решта символів - цифри
        if not phone[1:].replace('-', '').isdigit():
            return False, "Phone number must contain only digits after +"
            
        # Перевіряємо мінімальну довжину (включаючи '+' і код країни)
        if len(phone) < 9:
            return False, "Phone number is too short"
            
        return True, phone
        
    except Exception as e:
        logging.error(f"Phone validation error: {e}")
        return False, str(e)

@app.route('/save_delivery_address', methods=['POST'])
def save_delivery_address():
    try:
        user_id = session['user_id']
        address_data = {
            'full_name': request.form['full_name'],
            'phone': request.form['phone'],
            'country': request.form['country'],
            'postal_code': request.form['postal_code'],
            'city': request.form['city'],
            'street': request.form['street'],
            'is_default': not bool(get_user_addresses(user_id))  # Перша адреса буде default
        }

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO delivery_addresses 
                (user_id, full_name, phone, country, postal_code, city, street, is_default)
                VALUES (%(user_id)s, %(full_name)s, %(phone)s, %(country)s, 
                        %(postal_code)s, %(city)s, %(street)s, %(is_default)s)
            """, {**address_data, 'user_id': user_id})
            conn.commit()

        flash(_("Address saved successfully"), "success")
        return redirect(url_for('public_cart'))

    except Exception as e:
        logging.error(f"Error saving address: {e}")
        flash(_("Error saving address"), "error")
        return redirect(url_for('public_cart'))


def validate_eu_vat(vat_number):
    """Validates European VAT number format"""
    patterns = {
        'AT': r'^ATU\d{8}$',                      # Austria
        'BE': r'^BE0\d{9}$',                      # Belgium
        'BG': r'^BG\d{9,10}$',                    # Bulgaria
        'CY': r'^CY\d{8}[A-Z]$',                  # Cyprus
        'CZ': r'^CZ\d{8,10}$',                    # Czech Republic
        'DE': r'^DE\d{9}$',                       # Germany
        'DK': r'^DK\d{8}$',                       # Denmark
        'EE': r'^EE\d{9}$',                       # Estonia
        'EL': r'^EL\d{9}$',                       # Greece
        'ES': r'^ES[A-Z0-9]\d{7}[A-Z0-9]$',      # Spain
        'FI': r'^FI\d{8}$',                       # Finland
        'FR': r'^FR[A-HJ-NP-Z0-9]\d{9}$',        # France
        'GB': r'^GB(\d{9}|\d{12}|GD\d{3}|HA\d{3})$', # United Kingdom
        'HR': r'^HR\d{11}$',                      # Croatia
        'HU': r'^HU\d{8}$',                       # Hungary
        'IE': r'^IE\d{7}[A-Z]{1,2}$',            # Ireland
        'IT': r'^IT\d{11}$',                      # Italy
        'LT': r'^LT(\d{9}|\d{12})$',             # Lithuania
        'LU': r'^LU\d{8}$',                      # Luxembourg
        'LV': r'^LV\d{11}$',                     # Latvia
        'MT': r'^MT\d{8}$',                      # Malta
        'NL': r'^NL\d{9}B\d{2}$',               # Netherlands
        'PL': r'^PL\d{10}$',                     # Poland
        'PT': r'^PT\d{9}$',                      # Portugal
        'RO': r'^RO\d{2,10}$',                   # Romania
        'SE': r'^SE\d{12}$',                     # Sweden
        'SI': r'^SI\d{8}$',                      # Slovenia
        'SK': r'^SK\d{10}$'                      # Slovakia
    }

    try:
        # Очищаємо номер від пробілів та переводимо у верхній регістр
        vat_number = vat_number.replace(' ', '').upper()
        
        # Отримуємо код країни (перші 2 символи)
        country_code = vat_number[:2]
        
        if country_code not in patterns:
            return {
                'valid': False,
                'message': f"Unknown country code: {country_code}",
                'country': None
            }

        # Перевіряємо формат за допомогою регулярного виразу
        if re.match(patterns[country_code], vat_number):
            # Тут можна додати API перевірку через VIES (EU VAT validation service)
            return {
                'valid': True,
                'message': "VAT number format is valid",
                'country': country_code
            }
        else:
            return {
                'valid': False,
                'message': f"Invalid format for {country_code} VAT number",
                'country': country_code
            }

    except Exception as e:
        logging.error(f"Error validating VAT number: {e}")
        return {
            'valid': False,
            'message': "Error validating VAT number",
            'country': None
        }




# Сторінка "Доставка і оплата"
@app.route('/shipping-payment')
def shipping_payment():
    return render_template('public/shipping_payment.html')

# Сторінка "Повернення та обмін"
@app.route('/returns')
def returns():
    return render_template('public/returns.html')

# Сторінка "Контакти"
@app.route('/contacts')
def contacts():
    return render_template('public/contacts.html')



# ______________________________   Тест API ________________________________
# __________________________________________________________________________
def get_public_api_price(article_numbers):
    """
    Функція для отримання цін та інформації про запчастини через зовнішнє API
    
    Args:
        article_numbers (list): Список артикулів для пошуку
        
    Returns:
        dict: Результати пошуку або помилка
    """
    try:
        # API параметри
        api_url = "https://autocarat.de/api/search.php"  # Правильний URL API
        api_token = os.environ.get('API_CONNECT', 'ee76b66cc64b642563991955e8d65b4844bca449')
        
        logging.info(f"Making API request for {len(article_numbers)} articles")
        
        # Формуємо URL з параметрами для GET запиту
        params = {'t': api_token}
        
        # Додаємо артикули як параметри numbers[]
        for article in article_numbers:
            params.setdefault('numbers[]', []).append(article.strip().upper())
        
        # Виконуємо запит
        response = requests.get(api_url, params=params, timeout=15)
        
        # Перевіряємо статус відповіді
        if response.status_code == 200:
            result = response.json()
            logging.info(f"API returned info for {len(result.get('results', {}))} articles")
            return result
        else:
            logging.error(f"API request failed with status {response.status_code}: {response.text}")
            return {"error": f"API request failed with status {response.status_code}"}
            
    except requests.RequestException as e:
        logging.error(f"API request error: {e}")
        return {"error": f"Connection error: {str(e)}"}
        
    except ValueError as e:
        logging.error(f"API JSON parsing error: {e}")
        return {"error": "Error parsing API response"}
        
    except Exception as e:
        logging.error(f"Unexpected error in API request: {e}", exc_info=True)
        return {"error": f"Unexpected error: {str(e)}"}

@app.route('/api-search', methods=['GET', 'POST'])
def api_part_search():
    """
    Публічний маршрут для пошуку запчастин через API
    """
    try:
        if request.method == 'POST':
            # Отримуємо введені артикули
            articles_input = request.form.get('articles', '').strip()
            
            if not articles_input:
                flash(_("Please enter at least one article number"), "warning")
                return render_template('public/api_search.html')
            
            # Розділяємо введені артикули (можуть бути розділені комами, пробілами або переносами рядків)
            articles = re.split(r'[\s,;]+', articles_input)
            articles = [a.strip().upper() for a in articles if a.strip()]
            
            # Обмежуємо кількість артикулів для одного запиту
            max_articles = 10
            if len(articles) > max_articles:
                flash(_("Maximum {max_articles} articles per request. Only first {max_articles} will be processed.").format(
                    max_articles=max_articles), "warning")
                articles = articles[:max_articles]
            
            # Викликаємо API
            api_response = get_public_api_price(articles)
            
            # Перевіряємо на помилки
            if "error" in api_response:
                flash(_(api_response["error"]), "error")
                return render_template('public/api_search.html', articles=articles_input)
            
            # Формуємо результати для відображення
            return render_template(
                'public/api_search_results.html',
                articles=articles,
                results=api_response.get("results", {}),
                input_text=articles_input
            )
            
        # GET запит - показуємо форму пошуку
        return render_template('public/api_search.html')
        
    except Exception as e:
        logging.error(f"Error in API search route: {e}", exc_info=True)
        flash(_("An error occurred while processing your request"), "error")
        return render_template('public/api_search.html')


@app.route('/api-add-to-cart-bulk', methods=['POST'])
def public_add_to_cart_bulk():
    """Додає вибрані товари з результатів API пошуку в кошик"""
    try:
        # Отримуємо вибрані товари
        selected_parts = request.form.getlist('selected_parts[]')
        
        if not selected_parts:
            flash(_("No parts selected"), "warning")
            return redirect(url_for('api_part_search'))
        
        # Відновлюємо вихідний текст для повторного пошуку, якщо потрібно
        input_text = request.form.get('input_text', '')
        
        # Повторно виконуємо пошук для отримання даних
        articles = re.split(r'[\s,;]+', input_text)
        articles = [a.strip().upper() for a in articles if a.strip()]
        
        api_response = get_public_api_price(articles)
        
        if "error" in api_response:
            flash(_(api_response["error"]), "error")
            return redirect(url_for('api_part_search'))
        
        results = api_response.get("results", {})
        
        # Ініціалізуємо кошик, якщо потрібно
        if 'public_cart' not in session:
            session['public_cart'] = {}
        
        # Додаємо кожний вибраний товар у кошик
        added_count = 0
        for part_key in selected_parts:
            try:
                article, index = part_key.split(':')
                index = int(index)
                
                # Отримуємо дані товару з результатів
                if article in results and index < len(results[article]):
                    part_data = results[article][index]
                    quantity = int(request.form.get(f'quantity_{article}_{index}', 1))
                    
                    # Форматуємо для кошика
                    price_eur = part_data['cent'] / 100  # Конвертуємо центи в євро
                    
                    # Додаємо в кошик
                    if article not in session['public_cart']:
                        session['public_cart'][article] = {}
                    
                    # Використовуємо brand як table_name для сумісності з існуючою структурою
                    table_name = f"api_{part_data['make'].lower()}"
                    
                    session['public_cart'][article][table_name] = {
                        'price': float(price_eur),
                        'quantity': quantity,
                        'brand_id': None,  # API не надає brand_id
                        'comment': f"{part_data['title']} - {part_data['term']} days"
                    }
                    
                    added_count += 1
            except Exception as e:
                logging.error(f"Error adding item to cart: {e}", exc_info=True)
                continue
        
        # Явно позначаємо сесію як модифіковану
        session.modified = True
        
        if added_count > 0:
            flash(_("{count} items added to cart").format(count=added_count), "success")
            return redirect(url_for('public_cart'))
        else:
            flash(_("No items were added to cart"), "warning")
            return redirect(url_for('api_part_search'))
        
    except Exception as e:
        logging.error(f"Error in bulk add to cart: {e}", exc_info=True)
        flash(_("An error occurred while adding items to cart"), "error")
        return redirect(url_for('api_part_search'))



# __________________________________________________________________
# __________________________________________________________________
# __________________________________________________________________
# __________________________________________________________________
# __________________________________________________________________


# Add near other template filters
@app.template_filter('from_json')
def from_json(value):
    """Convert JSON string to Python dictionary"""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except:
        return {}

@app.route('/validate_phone', methods=['POST'])
def validate_phone_route():
    try:
        phone = request.json.get('phone', '')
        is_valid, message = validate_phone(phone)  # Використовуємо існуючу функцію
        return jsonify({
            'valid': is_valid,
            'message': message
        })
    except Exception as e:
        logging.error(f"Error validating phone: {e}")
        return jsonify({
            'valid': False,
            'message': _("Error validating phone number")
        }), 500

@app.route('/validate-vat', methods=['POST'])
def validate_vat_route():
    """API endpoint для перевірки VAT номера"""
    try:
        vat_number = request.json.get('vat_number', '')
        result = validate_eu_vat(vat_number)
        return jsonify(result)
    except Exception as e:
        logging.error(f"Error in validate_vat_route: {e}")
        return jsonify({
            'valid': False,
            'message': "Server error during validation",
            'country': None
        }), 500



# Заміните існуючу функцію get_categories_for_menu()
def get_categories_for_menu():
    """Отримує повну ієрархію категорій для меню"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Отримуємо поточну мову
        lang = session.get('language', 'sk')
        
        # Отримуємо всі категорії одним запитом
        cursor.execute(f"""
            SELECT 
                id, 
                name_{lang} as name,
                name_uk as name_uk, 
                name_en as name_en,
                name_sk as name_sk,
                name_pl as name_pl,
                parent_id,
                slug
            FROM categories 
            ORDER BY order_index
        """)
        
        # Конвертуємо результат в список словників
        all_categories = [dict(row) for row in cursor.fetchall()]
        
        # Створюємо словник для швидкого доступу до категорій за ID
        categories_dict = {cat['id']: cat for cat in all_categories}
        
        # Створюємо ієрархічну структуру
        for category in all_categories:
            category['subcategories'] = []
        
        # Заповнюємо підкатегорії
        main_categories = []
        for category in all_categories:
            if category['parent_id'] is None:
                main_categories.append(category)
            else:
                parent = categories_dict.get(category['parent_id'])
                if parent:
                    parent.setdefault('subcategories', []).append(category)
        
        cursor.close()
        conn.close()
        return main_categories
        
    except Exception as e:
        logging.error(f"Error getting main categories: {e}", exc_info=True)
        return []


def get_subcategories(parent_id):
    """Отримує підкатегорії для вказаної батьківської категорії"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Отримуємо поточну мову
        lang = session.get('language', 'uk')
        
        # Запит для отримання підкатегорій
        cursor.execute(f"""
            SELECT 
                id, 
                name_{lang} as name,
                name_uk as name_uk, 
                name_en as name_en,
                name_sk as name_sk,
                name_pl as name_pl,
                slug
            FROM categories 
            WHERE parent_id = %s 
            ORDER BY order_index
        """, (parent_id,))
        
        # Конвертуємо в звичайні словники
        subcategories = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        return subcategories
        
    except Exception as e:
        logging.error(f"Error getting subcategories: {e}", exc_info=True)
        return []

@app.context_processor
def inject_category_function():
    """Додає функцію для отримання категорій до контексту шаблону"""
    
    def get_main_categories():
        """Отримує ієрархічну структуру категорій для меню"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо всі категорії
            cursor.execute("""
                SELECT id, name_uk, name_en, name_sk, name_pl, parent_id, slug
                FROM categories
                ORDER BY order_index, id
            """)
            all_cats = cursor.fetchall()
            
            # Конвертуємо в список словників
            categories = [dict(row) for row in all_cats]
            
            # Створюємо словник для швидкого доступу до категорій за ID
            categories_by_id = {}
            for category in categories:
                categories_by_id[category['id']] = category
                # Додаємо порожній список для підкатегорій
                category['subcategories'] = []
            
            # Заповнюємо ієрархію
            root_categories = []
            for category in categories:
                if category['parent_id'] is None:
                    root_categories.append(category)
                else:
                    parent = categories_by_id.get(category['parent_id'])
                    if parent:
                        parent['subcategories'].append(category)
            
            cursor.close()
            conn.close()
            return root_categories
            
        except Exception as e:
            logging.error(f"Error getting categories: {e}", exc_info=True)
            return []
    
    return {'get_main_categories': get_main_categories}

# Розширена функція inject_template_vars з підтримкою категорій
@app.context_processor
def inject_template_vars():
    """Інжекція змінних для всіх шаблонів"""
    
    # Поточний рік для футера
    def today_year():
        return datetime.now().year
    
    # Підрахунок кількості товарів у кошику
    def get_user_cart_count():
        user_id = session.get('user_id')
        if user_id:
            # Для авторизованих користувачів рахуємо з бази даних
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COALESCE(SUM(quantity), 0) 
                    FROM cart 
                    WHERE user_id = %s
                """, (user_id,))
                count = cursor.fetchone()[0]
                # Оновлюємо cart_count в сесії
                session['cart_count'] = int(count)
                session.modified = True
                return int(count)
            except Exception as e:
                logging.error(f"Error getting cart count: {e}")
                return session.get('cart_count', 0)
            finally:
                if 'cursor' in locals():
                    cursor.close()
                if 'conn' in locals():
                    conn.close()
        else:
            # Для неавторизованих користувачів, рахуємо з сесії
            cart = session.get('public_cart', {})
            if not cart:
                session['cart_count'] = 0
                session.modified = True
                return 0
                
            total_count = 0
            # ВИПРАВЛЕНО: правильно рахуємо загальну кількість товарів
            for article_data in cart.values():
                if isinstance(article_data, dict):
                    for item_data in article_data.values():
                        if isinstance(item_data, dict):
                            total_count += item_data.get('quantity', 0)
            
            # Оновлюємо cart_count в сесії
            session['cart_count'] = total_count
            session.modified = True
            return total_count
    
    # Функція для отримання підкатегорій
    def get_subcategories(parent_id):
        """Отримує підкатегорії для вказаної батьківської категорії"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо поточну мову
            lang = session.get('language', 'sk')
            
            # Запит для отримання підкатегорій
            cursor.execute(f"""
                SELECT 
                    id, 
                    name_{lang} as name,
                    name_uk as name_uk, 
                    name_en as name_en,
                    name_sk as name_sk,
                    name_pl as name_pl,
                    slug
                FROM categories 
                WHERE parent_id = %s 
                ORDER BY order_index
            """, (parent_id,))
            
            # Конвертуємо в звичайні словники
            subcategories = [dict(row) for row in cursor.fetchall()]
            
            cursor.close()
            conn.close()
            return subcategories
            
        except Exception as e:
            logging.error(f"Error getting subcategories: {e}", exc_info=True)
            return []
    
    # Повертаємо всі необхідні змінні в єдиному словнику
    return dict(
        get_user_cart_count=get_user_cart_count,
        today_year=today_year,
        LANGUAGES=LANGUAGES,
        get_main_categories=get_categories_for_menu,
        get_subcategories=get_subcategories
    )

@app.template_filter('tojson')
def filter_tojson(obj):
    """Фільтр для перетворення Python об'єкту в JSON рядок"""
    import json
    return json.dumps(obj)

# Функція для реєстрації нового користувача
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone = request.form['phone']  # Нове поле

        # Валідація телефону
        is_valid_phone, phone_message = validate_phone(phone)
        if not is_valid_phone:
            flash(_(phone_message), "error")
            return render_template('auth/register.html')

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Перевірка наявності користувача
                cursor.execute("""
                    SELECT id 
                    FROM users 
                    WHERE username = %s 
                    OR email = %s 
                    OR phone = %s
                """, (username, email, phone_message))
                
                if cursor.fetchone():
                    flash(_("Username, email or phone already registered."), "error")
                    return render_template('auth/register.html')

                # Хешування пароля
                hashed_password = hash_password(password)

                # Додавання нового користувача
                cursor.execute("""
                    INSERT INTO users (username, email, password_hash, phone)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (username, email, hashed_password, phone_message))
                user_id = cursor.fetchone()[0]

                # Отримуємо ID ролі 'public'
                cursor.execute("SELECT id FROM roles WHERE name = 'public'")
                public_role = cursor.fetchone()
                
                # Призначаємо роль користувачу
                cursor.execute("""
                    INSERT INTO user_roles (user_id, role_id, assigned_at)
                    VALUES (%s, %s, NOW())
                """, (user_id, public_role[0]))

                # Автоматична авторизація
                session['user_id'] = user_id
                session['username'] = username
                session['role'] = 'public'

                conn.commit()
                logging.info(f"New user registered: user_id={user_id}, username={username}, role=public")
                flash(_("Registration successful! You are now logged in."), "success")
                return redirect(url_for('index'))

        except Exception as e:
            logging.error(f"Error during registration: {e}", exc_info=True)
            flash(_("Registration failed. Please try again."), "error")
            return render_template('auth/register.html')

    return render_template('auth/register.html')

# сторінка про нас public
@app.route('/about')
def about():
    return render_template('public/about.html')

# Функція для авторизації користувача
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        logging.debug("Verifying password")

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Спочатку перевіряємо користувача
            cursor.execute("""
                SELECT id, username, password_hash, email
                FROM users 
                WHERE username = %s
            """, (username,))
            
            user = cursor.fetchone()
            
            if user and verify_password(password, user['password_hash']):
                # Тепер перевіряємо роль
                cursor.execute("""
                    SELECT r.name as role
                    FROM user_roles ur
                    JOIN roles r ON ur.role_id = r.id
                    WHERE ur.user_id = %s
                """, (user['id'],))
                
                role_row = cursor.fetchone()
                role = role_row['role'] if role_row else 'public'
                
                # Зберігаємо дані в сесії
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = role
                
                logging.info(f"User logged in: user_id={user['id']}, username={user['username']}, role={role}")
                
                # Перевіряємо, чи є URL для перенаправлення
                next_url = session.get('next_url')
                if next_url:
                    session.pop('next_url', None)
                    return redirect(next_url)
                
                return redirect(url_for('index'))
            
            flash(_("Invalid username or password"), "error")
            return redirect(url_for('login'))

    return render_template('auth/login.html')

def get_user_companies(user_id):
    """Get all saved companies for a user"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("""
                SELECT * FROM user_companies 
                WHERE user_id = %s 
                ORDER BY is_default DESC, created_at DESC
            """, (user_id,))
            return cursor.fetchall()
    except Exception as e:
        logging.error(f"Error getting user companies: {e}")
        return []


def send_email(to_email, subject, ordered_items, delivery_data, lang='en'):
    """
    Відправляє email з деталями замовлення на вказаній мові з HTML-форматуванням
    """
    try:
        logging.info(f"Sending email to {to_email} with language {lang}")
        
        # Налаштування SMTP
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT"))
        sender_email = os.getenv("SMTP_EMAIL")
        sender_password = os.getenv("SMTP_PASSWORD")
        
        # Використовуємо sender_email як bcc_email для уникнення дублювання
        bcc_email = sender_email
        
        if not sender_email or not sender_password:
            logging.error("SMTP credentials are not set in environment variables")
            return False

        # Словарь переводов для каждого языка
        translations = {
            'sk': {
                'subject': 'Potvrdenie objednávky',
                'greeting': 'Ďakujeme za Vašu objednávku!',
                'order_details': 'Detaily objednávky:',
                'delivery_info': 'Dodacie údaje:',
                'name': 'Meno:',
                'phone': 'Telefón:',
                'address': 'Adresa:',
                'article': 'Kód:',
                'price': 'Cena:',
                'quantity': 'Množstvo:',
                'total': 'Celkom:',
                'in_stock': 'Na sklade',
                'delivery_time': 'Dodacia lehota:',
                'order_submitted': 'Vaše objednávka bola úspešne prijatá',
                'thank_you': 'Ďakujeme za Váš nákup!',
                'contact_us': 'V prípade otázok nás kontaktujte',
                'footer_text': 'Tento e-mail bol vygenerovaný automaticky. Prosím, neodpovedajte naň.',
                'invoice_note': 'V najbližšom čase Vám zašleme faktúru na úhradu.'
            },
            'en': {
                'subject': 'Order Confirmation',
                'greeting': 'Thank you for your order!',
                'order_details': 'Order details:',
                'delivery_info': 'Delivery information:',
                'name': 'Name:',
                'phone': 'Phone:',
                'address': 'Address:',
                'article': 'Code:',
                'price': 'Price:',
                'quantity': 'Quantity:',
                'total': 'Total:',
                'in_stock': 'In Stock',
                'delivery_time': 'Delivery time:',
                'order_submitted': 'Your order has been successfully submitted',
                'thank_you': 'Thank you for your purchase!',
                'contact_us': 'If you have any questions, please contact us',
                'footer_text': 'This email was generated automatically. Please do not reply to it.',
                'invoice_note': 'We will send you an invoice for payment in the near future.'
            },
            'uk': {
                'subject': 'Підтвердження замовлення',
                'greeting': 'Дякуємо за ваше замовлення!',
                'order_details': 'Деталі замовлення:',
                'delivery_info': 'Інформація про доставку:',
                'name': 'Ім\'я:',
                'phone': 'Телефон:',
                'address': 'Адреса:',
                'article': 'Код:',
                'price': 'Ціна:',
                'quantity': 'Кількість:',
                'total': 'Загалом:',
                'in_stock': 'В наявності',
                'delivery_time': 'Час доставки:',
                'order_submitted': 'Ваше замовлення успішно прийнято',
                'thank_you': 'Дякуємо за покупку!',
                'contact_us': 'Якщо у вас є питання, будь ласка, зв\'яжіться з нами',
                'footer_text': 'Цей лист згенеровано автоматично. Будь ласка, не відповідайте на нього.',
                'invoice_note': 'Найближчим часом ми надішлемо вам рахунок для оплати.'
            },
            'pl': {
                'subject': 'Potwierdzenie zamówienia',
                'greeting': 'Dziękujemy za złożenie zamówienia!',
                'order_details': 'Szczegóły zamówienia:',
                'delivery_info': 'Informacje o dostawie:',
                'name': 'Imię:',
                'phone': 'Telefon:',
                'address': 'Adres:',
                'article': 'Kod:',
                'price': 'Cena:',
                'quantity': 'Ilość:',
                'total': 'Suma:',
                'in_stock': 'W magazynie',
                'delivery_time': 'Czas dostawy:',
                'order_submitted': 'Twoje zamówienie zostało pomyślnie złożone',
                'thank_you': 'Dziękujemy za zakupy!',
                'contact_us': 'W razie pytań prosimy o kontakt',
                'footer_text': 'Ten e-mail został wygenerowany automatycznie. Prosimy na niego nie odpowiadać.',
                'invoice_note': 'W najbliższym czasie wyślemy Państwu fakturę do zapłaty.'
            }
        }

        # Используем перевод для выбранного языка или английский как запасной
        t = translations.get(lang, translations['en'])
        
        # Рассчитываем общую сумму для шаблона
        total_sum = 0
        for item in ordered_items:
            price = float(item['price'])
            quantity = int(item['quantity'])
            total_sum += price * quantity

        # Рендерим текстовую версию
        text_content = render_template(
            'emails/order_confirmation.txt',
            t=t,
            delivery_data=delivery_data,
            ordered_items=ordered_items,
            total_sum=total_sum,
            subject=subject or t['subject']
        )

        # Рендерим HTML версию
        html_content = render_template(
            'emails/order_confirmation.html',
            t=t,
            delivery_data=delivery_data,
            ordered_items=ordered_items,
            total_sum=total_sum,
            subject=subject or t['subject'],
            current_year=datetime.now().year
        )

        # Формируем сообщение с текстовой и HTML версиями
        message = MIMEMultipart('alternative')
        message["From"] = sender_email
        message["To"] = to_email
        message["Subject"] = subject if subject else t['subject']
        # НЕ додаємо BCC в заголовки, щоб не було видно в листі
        
        # Добавляем обе версии
        message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

        # Отправка email
        try:
            # Используем SSL для порта 465
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            
            # Устанавливаем уровень отладки на 0 (отключаем подробное логирование)
            server.set_debuglevel(0)
            
            # Аутентификация
            server.login(sender_email, sender_password)
            
            # Отправка (включаем основного получателя и BCC)
            recipients = [to_email]
            # Додаємо BCC тільки якщо він відрізняється від основного отримувача
            if bcc_email and bcc_email != to_email:
                recipients.append(bcc_email)
                
            server.sendmail(sender_email, recipients, message.as_string())
            logging.info(f"Email successfully sent to {to_email}" + 
                         (f" and BCC ({bcc_email})" if bcc_email != to_email else ""))
            server.quit()
            return True
            
        except smtplib.SMTPConnectError as e:
            logging.error(f"SMTP Connection Error: {e}")
            return False
        except smtplib.SMTPAuthenticationError as e:
            logging.error(f"SMTP Authentication Error: {e}")
            return False
        except smtplib.SMTPException as e:
            logging.error(f"SMTP Error: {e}")
            return False
        except ConnectionError as e:
            logging.error(f"Connection Error: {e}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to send email to {to_email}: {str(e)}")
        return False

@app.route('/public_place_order', methods=['POST'])
def public_place_order():
    """Creates order for public user with delivery address and invoice details"""
    logging.info("=== Starting public_place_order process ===")
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash(_("Please log in to place an order."), "error")
            return redirect(url_for('login'))

        # Отримуємо метод доставки з форми
        shipping_method = request.form.get('shipping_method', 'standard')
            
        # Додаємо детальний лог для діагностики
        logging.info(f"Processing order for user_id: {user_id}, username: {session.get('username')}")

        # Функція для серіалізації datetime в JSON
        def json_serial(obj):
            """Конвертує нестандартні типи для JSON"""
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(f"Type {type(obj)} not serializable")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get delivery data
        delivery_data = {}
        address_id = request.form.get('delivery_address')
        use_new_address = request.form.get('use_new_address') == '1'
        save_address = request.form.get('save_address') == 'on'
        
        logging.debug(f"Form data: {dict(request.form)}")
        logging.debug(f"Address ID: {address_id}, Use new: {use_new_address}, Save: {save_address}")

        if address_id and not use_new_address:
            # Using existing address
            logging.info(f"Using existing address ID: {address_id}")
            cursor.execute("""
                SELECT * FROM delivery_addresses 
                WHERE id = %s AND user_id = %s
            """, (address_id, user_id))
            address = cursor.fetchone()
            if address:
                delivery_data = dict(address)
                # Важливо - конвертуємо datetime поля
                if 'created_at' in delivery_data and delivery_data['created_at']:
                    delivery_data['created_at'] = delivery_data['created_at'].isoformat()
                logging.debug(f"Found existing address: {delivery_data}")
            else:
                flash(_("Selected address not found"), "error")
                return redirect(url_for('public_cart'))
        else:
            # Using new address
            delivery_data = {
                'full_name': request.form.get('full_name'),
                'phone': request.form.get('phone'),
                'country': request.form.get('country'),
                'postal_code': request.form.get('postal_code'),
                'city': request.form.get('city'),
                'street': request.form.get('street')
            }
            
            # Зберігаємо нову адресу, якщо вибрана опція
            if save_address:
                logging.info(f"Saving new address for user {user_id}")
                
                # Перевіряємо, чи є у користувача інші адреси, щоб визначити is_default
                cursor.execute("SELECT COUNT(*) FROM delivery_addresses WHERE user_id = %s", (user_id,))
                address_count = cursor.fetchone()[0]
                is_default = address_count == 0  # якщо це перша адреса, робимо її стандартною
                
                # Вставляємо нову адресу в базу даних
                cursor.execute("""
                    INSERT INTO delivery_addresses 
                    (user_id, full_name, phone, country, postal_code, city, street, is_default, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                """, (
                    user_id,
                    delivery_data['full_name'],
                    delivery_data['phone'],
                    delivery_data['country'],
                    delivery_data['postal_code'],
                    delivery_data['city'],
                    delivery_data['street'],
                    is_default
                ))
                
                new_address_id = cursor.fetchone()[0]
                logging.info(f"New address saved with ID: {new_address_id}, is_default: {is_default}")

        # Get invoice details
        needs_invoice = request.form.get('needs_invoice') == 'on'
        invoice_details = None
        
        if needs_invoice:
            company_id = request.form.get('company_id')
            if company_id:
                # Using existing company
                logging.info(f"Using existing company ID: {company_id}")
                cursor.execute("""
                    SELECT * FROM user_companies 
                    WHERE id = %s AND user_id = %s
                """, (company_id, user_id))
                company = cursor.fetchone()
                
                if company:
                    invoice_details = dict(company)
                    # Важливо - конвертуємо datetime поля
                    if 'created_at' in invoice_details and invoice_details['created_at']:
                        invoice_details['created_at'] = invoice_details['created_at'].isoformat()
                    logging.debug(f"Found existing company: {invoice_details}")
                else:
                    flash(_("Selected company not found"), "error")
                    return redirect(url_for('public_cart'))
            else:
                # Using new company details
                invoice_details = {
                    'company_name': request.form.get('company_name'),
                    'vat_number': request.form.get('vat_number'),
                    'registration_number': request.form.get('registration_number'),
                    'address': request.form.get('company_address')
                }

        total_price = Decimal('0')
        order_items = []
        email_items = []  # Для відправки листа
        
        # Спочатку шукаємо товари у базі даних для авторизованих користувачів
        cursor.execute("""
            SELECT article, table_name, base_price, final_price as price, 
                   quantity, brand_id, comment
            FROM cart 
            WHERE user_id = %s
        """, (user_id,))
        
        db_cart_items = cursor.fetchall()
        logging.info(f"Found {len(db_cart_items)} items in database cart for user {user_id}")
        
        # Обробляємо товари з бази даних
        for item in db_cart_items:
            item_price = Decimal(str(item['price']))
            item_quantity = int(item['quantity'])
            item_total = item_price * item_quantity
            total_price += item_total
            
            order_items.append({
                'article': item['article'],
                'table_name': item['table_name'],
                'price': item_price,
                'quantity': item_quantity,
                'total_price': item_total,
                'brand_id': item['brand_id'],
                'comment': item['comment'] or ''
            })
            
            # Додаємо інформацію для листа
            if item['table_name'] == 'stock':
                delivery_time = _("In Stock")
            else:
                cursor.execute("""
                    SELECT delivery_time FROM price_lists 
                    WHERE table_name = %s
                """, (item['table_name'],))
                result = cursor.fetchone()
                delivery_time_str = result['delivery_time'] if result else '7-14'
                delivery_time = _("In Stock") if delivery_time_str == '0' else f"{delivery_time_str} {_('days')}"
            
            email_items.append({
                'article': item['article'],
                'price': float(item_price),
                'quantity': item_quantity,
                'delivery_time': delivery_time
            })

        # Тепер перевіряємо сесію - для зворотної сумісності
        cart = session.get('public_cart', {})
        logging.debug(f"Cart data in session: {cart}")
        
        # Обробка товарів з кошика в сесії
        for article, article_items in cart.items():
            for table_name, item_data in article_items.items():
                if 'price' not in item_data or 'quantity' not in item_data:
                    logging.warning(f"Invalid item data: {item_data}")
                    continue
                    
                item_price = Decimal(str(item_data['price']))
                item_quantity = int(item_data['quantity']) 
                item_total = item_price * item_quantity
                total_price += item_total
                
                order_items.append({
                    'article': article,
                    'table_name': table_name,
                    'price': item_price,
                    'quantity': item_quantity,
                    'total_price': item_total,
                    'brand_id': item_data.get('brand_id'),
                    'comment': item_data.get('comment', '')
                })

                # Додаємо інформацію для листа
                if table_name == 'stock':
                    delivery_time = _("In Stock")
                else:
                    cursor.execute("""
                        SELECT delivery_time FROM price_lists 
                        WHERE table_name = %s
                    """, (table_name,))
                    result = cursor.fetchone()
                    delivery_time_str = result['delivery_time'] if result else '7-14'
                    delivery_time = _("In Stock") if delivery_time_str == '0' else f"{delivery_time_str} {_('days')}"
                
                email_items.append({
                    'article': article,
                    'price': float(item_price),
                    'quantity': item_quantity,
                    'delivery_time': delivery_time
                })

        logging.debug(f"Order items processed: {len(order_items)}")
        logging.debug(f"Total price calculated: {total_price}")
        
        if not order_items:
            logging.warning("No items to process in cart (neither in session nor database)")
            flash(_("Your cart is empty"), "error")
            return redirect(url_for('public_cart'))

        # Create order in database
        logging.debug("Creating order in database")
        cursor.execute("""
            INSERT INTO public_orders 
            (user_id, total_price, status, created_at, updated_at, delivery_address, needs_invoice, invoice_details, payment_status, shipping_method)
            VALUES (%s, %s, 'new', NOW(), NOW(), %s, %s, %s, 'unpaid', %s)
            RETURNING id
        """, (
            user_id,
            total_price,
            json.dumps(delivery_data, default=json_serial),
            needs_invoice,
            json.dumps(invoice_details, default=json_serial) if invoice_details else None,
            shipping_method
        ))
        
        order_id = cursor.fetchone()['id']
        logging.info(f"Created order with ID: {order_id}")

        # Add order details
        for item in order_items:
            cursor.execute("""
                INSERT INTO public_order_details 
                (order_id, article, table_name, price, quantity, total_price, comment, brand_id, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', NOW())
            """, (
                order_id,
                item['article'],
                item['table_name'],
                item['price'],
                item['quantity'],
                item['total_price'],
                item['comment'],
                item['brand_id']
            ))
        
        # Commit database changes early so that the order is saved even if email fails
        conn.commit()
        
        # Get user email for notification - додаємо username в запит
        cursor.execute("""
            SELECT id, username, email, preferred_language FROM users WHERE id = %s
        """, (user_id,))
        user_info = cursor.fetchone()

        logging.info(f"Getting email for user: {user_id}, found: {user_info and user_info['email']}")
        
        # Send email confirmation if user has email
        if user_info and user_info['email']:
            # Get user's preferred language or current interface language
            user_lang = user_info['preferred_language'] or session.get('language', 'sk')
            if user_lang == 'uk':  # Якщо мова українська, використовуємо словацьку
                user_lang = 'sk'
            
            # Перевіряємо, що email не містить поширені помилки друку
            recipient_email = user_info['email'].strip()
            if '@gmil.com' in recipient_email.lower():
                logging.warning(f"Detected typo in email: {recipient_email}, correcting to @gmail.com")
                recipient_email = recipient_email.lower().replace('@gmil.com', '@gmail.com')
            
            logging.info(f"Sending order confirmation email to {recipient_email} (user: {user_info['username']}) in {user_lang} language")
            
            # Використовуємо окремий try-except для відправки email, щоб не впливати на процес замовлення
            try:
                # Створення простого локального повідомлення у випадку, якщо SMTP не працює
                try:
                    email_sent = send_email(
                        to_email=recipient_email,
                        subject=f"Order #{order_id}", 
                        ordered_items=email_items,
                        delivery_data=delivery_data, 
                        lang=user_lang
                    )
                    
                    if email_sent:
                        logging.info(f"Email sent successfully to {recipient_email}")
                    else:
                        logging.warning(f"Failed to send email to {recipient_email}, but order was placed successfully")
                        
                        # Додаємо замовлення до черги для відправки пізніше
                        try:
                            # Зберігаємо у базі дані для повторної відправки листа пізніше
                            cursor.execute("""
                                INSERT INTO email_queue 
                                (recipient, subject, order_id, user_id, delivery_data, ordered_items, lang, created_at, status)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 'pending')
                            """, (
                                recipient_email,
                                f"Order #{order_id}",
                                order_id,
                                user_id,
                                json.dumps(delivery_data, default=json_serial),
                                json.dumps(email_items, default=json_serial),
                                user_lang
                            ))
                            conn.commit()
                            logging.info(f"Added email to queue for later delivery to {recipient_email}")
                        except Exception as queue_err:
                            logging.error(f"Failed to add email to queue: {queue_err}")
                            
                except Exception as email_err:
                    logging.error(f"Failed to send order confirmation email: {email_err}", exc_info=True)
            except Exception as outer_err:
                logging.error(f"Unexpected error in email sending block: {outer_err}", exc_info=True)
        
        # Clear cart in both session and database
        logging.info("Clearing cart")
        session['public_cart'] = {}
        session['cart_count'] = 0
        session.modified = True
        
        # Очищаємо корзину в базі даних
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()
        
        flash(_("Order placed successfully!"), "success")
        logging.info(f"Order {order_id} placed successfully, rendering confirmation")
        logging.info("=== Finished public_place_order process ===")

        # Рендеримо шаблон напряму замість редіректу
        try:
            order = get_order_by_id(order_id)
            if not order:
                flash(_("Order not found"), "error")
                return redirect(url_for('public_view_orders'))
            
            # Конвертуємо DictRow в звичайний словник
            order_dict = dict(order)
            
            # Отримуємо товари замовлення
            order_items = get_order_items(order_id)
            
            # Рендеримо шаблон напряму
            return render_template(
                'public/orders/confirmation.html',
                order=order_dict,
                order_items=order_items
            )
        except Exception as e:
            logging.error(f"Error displaying order confirmation: {e}", exc_info=True)
            flash(_("Error displaying order confirmation."), "error")
            return redirect(url_for('public_view_orders'))
    finally:
        if 'conn' in locals():
            conn.close()
        logging.info("=== Finished public_place_order process ===")








# сторінка успішного оформлення замовлення
@app.route('/order/confirmation/<order_id>')
def order_confirmation(order_id):
    """Відображає сторінку підтвердження замовлення"""
    logging.info(f"Displaying confirmation for order ID: {order_id}")
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash(_("Please log in to view order details."), "error")
            return redirect(url_for('login'))
        
        # Отримуємо деталі замовлення
        order = get_order_by_id(order_id)
        if not order:
            flash(_("Order not found"), "error")
            return redirect(url_for('public_view_orders'))
            
        if order['user_id'] != user_id:
            flash(_("Access denied"), "error")
            return redirect(url_for('public_view_orders'))
        
        # ВАЖЛИВО: Конвертуємо DictRow в звичайний словник
        order_dict = dict(order)
        
        # Отримуємо товари замовлення як окремий об'єкт
        order_items = get_order_items(order_id)
        logging.debug(f"Found {len(order_items)} items for order {order_id}")
        
        # Передаємо в шаблон два окремих параметри
        logging.info(f"Rendering confirmation template for order {order_id}")
        return render_template(
            'public/orders/confirmation.html',
            order=order_dict,
            order_items=order_items
        )
        
    except Exception as e:
        logging.error(f"Error displaying order confirmation: {e}", exc_info=True)
        flash(_("Error displaying order confirmation."), "error")
        return redirect(url_for('public_view_orders'))



def get_order_by_id(order_id):
    """Отримує інформацію про замовлення за його ID"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("""
                SELECT * FROM public_orders WHERE id = %s
            """, (order_id,))
            return cursor.fetchone()
    except Exception as e:
        logging.error(f"Error getting order by id: {e}", exc_info=True)
        return None

def get_order_items(order_id):
    """Отримує позиції замовлення за його ID"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("""
                SELECT od.*,
                       COALESCE(p.name_uk, od.article) as product_name,
                       b.name as brand_name
                FROM public_order_details od
                LEFT JOIN products p ON od.article = p.article
                LEFT JOIN brands b ON od.brand_id = b.id
                WHERE od.order_id = %s
            """, (order_id,))
            return cursor.fetchall()
    except Exception as e:
        logging.error(f"Error getting order items: {e}", exc_info=True)
        return []


@app.template_filter('datetime')
def format_datetime(value, format='%d.%m.%Y %H:%M'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    return value.strftime(format)

@app.template_filter('currency')
def format_currency(value):
    if value is None:
        return "€0.00"
    return f"€{float(value):.2f}"



@app.route('/cart/clear', methods=['POST'])
def cart_clear():
    if 'public_cart' in session:
        session.pop('public_cart')
    flash(_("Cart cleared successfully"), "success")
    return redirect(url_for('public_cart'))

@app.route('/public_orders')
def public_view_orders():
    """
    Відображає список замовлень публічного користувача
    """
    user_id = session.get('user_id')
    if not user_id:
        flash(_("Please log in to view your orders."), "error")
        return redirect(url_for('login'))
    
    orders = []
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Змініть запит для отримання кількості товарів у кожному замовленні
        cursor.execute("""
            SELECT o.*, COUNT(d.id) as items_count
            FROM public_orders o
            LEFT JOIN public_order_details d ON o.id = d.order_id
            WHERE o.user_id = %s
            GROUP BY o.id
            ORDER BY o.created_at DESC
        """, (user_id,))
        
        orders = cursor.fetchall()
        
    except Exception as e:
        logging.error(f"Error fetching orders: {e}", exc_info=True)
        flash(_("Error retrieving your orders"), "error")
    finally:
        if 'conn' in locals():
            conn.close()
    
    return render_template('public/orders/orders.html', orders=orders)

@app.route('/public_order/<int:order_id>')
def public_view_order_details(order_id):
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash(_("Please log in to view order details."), "error")
            return redirect(url_for('login'))

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get order details
        cursor.execute("""
            SELECT o.*, COUNT(od.id) as items_count
            FROM public_orders o
            LEFT JOIN public_order_details od ON o.id = od.order_id
            WHERE o.id = %s AND o.user_id = %s
            GROUP BY o.id
        """, (order_id, user_id))
        
        order = cursor.fetchone()

        if not order:
            flash(_("Order not found."), "error")
            return redirect(url_for('public_view_orders'))

        # Get order items with correct product name
        cursor.execute("""
            SELECT 
                od.*,
                COALESCE(p.name_uk, od.article) as product_name,
                b.name as brand_name
            FROM public_order_details od
            LEFT JOIN products p ON od.article = p.article
            LEFT JOIN brands b ON od.brand_id = b.id
            WHERE od.order_id = %s
            ORDER BY od.id
        """, (order_id,))
        
        order_items = cursor.fetchall()

        return render_template(
            'public/orders/order_details.html',
            order=order,
            items=order_items
        )

    except Exception as e:
        logging.error(f"Error viewing public order details: {e}", exc_info=True)
        flash(_("Error loading order details."), "error")
        return redirect(url_for('public_view_orders'))
    finally:
        if 'conn' in locals():
            conn.close()

# Функція для виходу з облікового запису
@app.route('/logout')
def logout():
    # Видаляємо інформацію про користувача
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('role', None)
    
    # Очищаємо кошик повністю
    session.pop('public_cart', None)
    session['cart_count'] = 0  # ДОДАНО: скидаємо лічильник
    session.modified = True    # ДОДАНО: позначаємо сесію як змінену
    
    logging.info("User logged out, cart cleared")
    flash(_("You have been logged out."), "info")
    return redirect(url_for('index'))



#Продукти зі складу на головній
@app.route('/api/products', methods=['GET'])
def api_products():
    """API endpoint для отримання додаткових продуктів без перезавантаження сторінки"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 8  # Кількість товарів на сторінці
        brand_id = request.args.get('brand', type=int)
        
        # Отримуємо мову з параметра запиту або з сесії
        lang = request.args.get('lang') or session.get('language', 'sk')
        
        # Підключення до бази даних
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # ПІДХІД, ЯК У index() - вибирає перше зображення з сортуванням за is_main DESC
        query = f"""
            SELECT 
                s.article, 
                s.price, 
                COALESCE(p.name_{lang}, p.name_uk, p.name_en, p.name_sk, s.article) as name, 
                b.name as brand_name,
                b.id as brand_id,
                (
                    SELECT image_url 
                    FROM product_images pi 
                    WHERE pi.product_article = s.article 
                    ORDER BY is_main DESC, id ASC 
                    LIMIT 1
                ) as image_url
            FROM stock s
            LEFT JOIN products p ON s.article = p.article
            LEFT JOIN brands b ON s.brand_id = b.id
            WHERE s.quantity > 0
        """
        params = []
        
        # Додаємо фільтр за брендом, якщо вказано
        if brand_id:
            query += " AND s.brand_id = %s"
            params.append(brand_id)
        
        # Додаємо сортування і пагінацію
        query += " ORDER BY s.price DESC LIMIT %s OFFSET %s"
        params.extend([per_page, (page - 1) * per_page])
        
        # Отримання товарів
        cursor.execute(query, params)
        products = cursor.fetchall()
        
        # Перевіряємо, чи є ще товари для наступної сторінки
        has_more = len(products) == per_page
        
        cursor.close()
        conn.close()
        
        # Повертаємо результат
        return jsonify({
            'products': [dict(p) for p in products],
            'next_page': page + 1,
            'has_more': has_more
        })
            
    except Exception as e:
        logging.error(f"Error in api_products: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Перегляд кошика публічного користувача
@app.route('/public_cart')
def public_cart():
    """View and manage shopping cart for any user (registered or anonymous)"""
    user_id = session.get('user_id')
    is_authenticated = user_id is not None
    
    cart_items = []
    total_price = Decimal('0')
    saved_addresses = []
    saved_companies = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Get current language
        lang = session.get('language', 'sk')
        
        # Get price lists information for delivery time
        cursor.execute("""
            SELECT table_name, delivery_time 
            FROM price_lists
        """)
        delivery_times = {row['table_name']: row['delivery_time'] for row in cursor.fetchall()}
        
        if is_authenticated:
            # Для авторизованих користувачів - отримуємо дані з БД
            # Get saved delivery addresses
            cursor.execute("""
                SELECT 
                    id, full_name, phone, country, 
                    postal_code, city, street, is_default
                FROM delivery_addresses
                WHERE user_id = %s
                ORDER BY is_default DESC, created_at DESC
            """, (user_id,))
            saved_addresses = cursor.fetchall()
            
            # Get saved companies
            cursor.execute("""
                SELECT 
                    id, company_name, vat_number, registration_number, 
                    address, is_default, created_at
                FROM user_companies
                WHERE user_id = %s
                ORDER BY is_default DESC, created_at DESC
            """, (user_id,))
            saved_companies = cursor.fetchall()
            
            # Отримуємо товари з кошика в базі даних
            cursor.execute("""
                SELECT 
                    c.article, 
                    c.table_name,
                    c.base_price,
                    c.quantity,
                    c.comment,
                    c.brand_id,
                    b.name as brand_name
                FROM cart c
                LEFT JOIN brands b ON c.brand_id = b.id
                WHERE c.user_id = %s
                ORDER BY c.added_at
            """, (user_id,))
            
            db_cart_items = cursor.fetchall()
            
            # Обробляємо товари з бази даних
            for item in db_cart_items:
                # Get item details from products table if available
                cursor.execute(f"""
                    SELECT 
                        article,
                        name_{lang} as name,
                        description_{lang} as description
                    FROM products
                    WHERE article = %s
                """, (item['article'],))
                product = cursor.fetchone()
                
                # Set defaults
                name = product['name'] if product and product['name'] else item['article']
                description = product['description'] if product and product['description'] else ''
                
                # Calculate values
                price = Decimal(str(item['base_price']))
                quantity = item['quantity']
                item_total = price * quantity
                total_price += item_total
                
                # Determine if item is in stock and delivery time
                in_stock = False
                delivery_time = None
                
                if item['table_name'] == 'stock':
                    in_stock = True
                    delivery_time = _("In Stock")
                else:
                    delivery_time_str = delivery_times.get(item['table_name'], '7-14')
                    in_stock = delivery_time_str == '0'
                    delivery_time = _("In Stock") if in_stock else f"{delivery_time_str} {_('days')}"
                
                # Create cart item object
                cart_item = {
                    'article': item['article'],
                    'name': name,
                    'description': description,
                    'brand_name': item['brand_name'],
                    'brand_id': item['brand_id'],
                    'price': float(price),
                    'quantity': quantity,
                    'total': float(item_total),
                    'table_name': item['table_name'],
                    'comment': item['comment'],
                    'in_stock': in_stock,
                    'delivery_time': delivery_time
                }
                
                cart_items.append(cart_item)
        else:
            # Для неавторизованих користувачів - отримуємо дані з сесії
            cart = session.get('public_cart', {})
            
            # Process cart items from session
            for article, article_items in cart.items():
                if not isinstance(article_items, dict):
                    continue
                
                for table_name, item_data in article_items.items():
                    if not isinstance(item_data, dict) or 'price' not in item_data:
                        continue
                    
                    # Get item details from DB by article
                    cursor.execute(f"""
                        SELECT 
                            article,
                            name_{lang} as name,
                            description_{lang} as description
                        FROM products
                        WHERE article = %s
                    """, (article,))
                    product = cursor.fetchone()
                    
                    # Set defaults if product not found
                    name = article
                    description = ""
                    
                    if product:
                        name = product['name'] or article
                        description = product['description'] or ''
                    
                    # Get brand name
                    brand_id = item_data.get('brand_id')
                    brand_name = "AutogroupEU"
                    
                    if brand_id:
                        cursor.execute("SELECT name FROM brands WHERE id = %s", (brand_id,))
                        brand_result = cursor.fetchone()
                        if brand_result:
                            brand_name = brand_result['name']
                    
                    # Calculate values
                    price = Decimal(str(item_data['price']))
                    quantity = item_data['quantity']
                    item_total = price * quantity
                    total_price += item_total
                    
                    # Determine if item is in stock and delivery time
                    in_stock = False
                    delivery_time = None
                    
                    if table_name == 'stock':
                        in_stock = True
                        delivery_time = _("In Stock")
                    else:
                        delivery_time_str = delivery_times.get(table_name, '7-14')
                        in_stock = delivery_time_str == '0'
                        delivery_time = _("In Stock") if in_stock else f"{delivery_time_str} {_('days')}"
                    
                    # Create cart item object
                    cart_item = {
                        'article': article,
                        'name': name,
                        'description': description,
                        'brand_name': brand_name,
                        'brand_id': brand_id,
                        'price': float(price),
                        'quantity': quantity,
                        'total': float(item_total),
                        'table_name': table_name,
                        'comment': item_data.get('comment', ''),
                        'in_stock': in_stock,
                        'delivery_time': delivery_time
                    }
                    
                    cart_items.append(cart_item)

    except Exception as e:
        logging.error(f"Error in public_cart: {e}", exc_info=True)
        flash(_("An error occurred while processing your request."), "error")
        cart_items = []
        total_price = Decimal('0')
        saved_addresses = []
        saved_companies = []

    finally:
        if 'conn' in locals():
            conn.close()

    return render_template(
        'public/cart/cart.html',
        cart_items=cart_items,
        total_price=total_price,
        saved_addresses=saved_addresses,
        saved_companies=saved_companies,
        is_authenticated=is_authenticated
    )


@app.route('/guest_checkout', methods=['POST'])
def guest_checkout():
    """Process checkout for guest users without registration"""
    try:
        # Отримуємо дані форми
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        country = request.form.get('country')
        postal_code = request.form.get('postal_code')
        city = request.form.get('city')
        street = request.form.get('street')
        shipping_method = request.form.get('shipping_method', 'pickup')

        # ДОДАНО: прапор і реквізити для фактури (для гостей)
        needs_invoice = request.form.get('needs_invoice') == 'on'
        invoice_details = None
        if needs_invoice:
            invoice_details = {
                'company_name': (request.form.get('company_name') or '').strip(),
                'vat_number': (request.form.get('vat_number') or '').strip(),
                'registration_number': (request.form.get('registration_number') or '').strip(),
                'address': (request.form.get('company_address') or '').strip()
            }
            # Необов'язкова базова перевірка формату VAT (лише якщо користувач ввів значення)
            if invoice_details['vat_number']:
                vat_check = validate_eu_vat(invoice_details['vat_number'])
                if not vat_check.get('valid'):
                    flash(_("Invalid VAT number format"), "error")
                    return redirect(url_for('public_cart'))

        # Валідація основних полів
        if not all([email, full_name, phone, country, city, street]):
            flash(_("All fields are required"), "error")
            return redirect(url_for('public_cart'))
        
        # Валідація телефону
        is_valid, phone_message = validate_phone(phone)
        if not is_valid:
            flash(_(phone_message), "error")
            return redirect(url_for('public_cart'))
        
        # Валідація email
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash(_("Invalid email format"), "error")
            return redirect(url_for('public_cart'))
        
        # Отримуємо корзину з сесії
        cart = session.get('public_cart', {})
        if not cart:
            flash(_("Your cart is empty"), "error")
            return redirect(url_for('public_cart'))
        
        # Підключення до бази даних
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Перевіряємо, чи існує користувач з таким email
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        # Генеруємо пароль для нового користувача
        hashed_password = hash_password(generate_token())
        
        if existing_user:
            # Використовуємо існуючий акаунт
            user_id = existing_user['id']
            logging.info(f"Using existing user account with ID: {user_id} for guest checkout")
        else:
            # Створюємо тимчасовий акаунт для гостя
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, phone)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (email, email, hashed_password, phone))
            
            user_id = cursor.fetchone()['id']
            
            # Призначаємо роль 'public'
            cursor.execute("SELECT id FROM roles WHERE name = 'public'")
            public_role_id = cursor.fetchone()['id']
            
            cursor.execute("""
                INSERT INTO user_roles (user_id, role_id, assigned_at)
                VALUES (%s, %s, NOW())
            """, (user_id, public_role_id))
        
        # Функція для серіалізації datetime в JSON
        def json_serial(obj):
            """Конвертує нестандартні типи для JSON"""
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(f"Type {type(obj)} not serializable")
        
        # Формуємо дані доставки
        delivery_data = {
            'full_name': full_name,
            'phone': phone,
            'country': country,
            'postal_code': postal_code,
            'city': city,
            'street': street,
            'shipping_method': shipping_method,
            # ДОДАНО: щоб відобразити на підтвердженні
            'needs_invoice': needs_invoice
        }
        
        # Обробка товарів з кошика
        total_price = Decimal('0')
        order_items = []
        email_items = []  # Для відправки листа
        
        for article, article_items in cart.items():
            for table_name, item_data in article_items.items():
                if 'price' not in item_data or 'quantity' not in item_data:
                    continue
                    
                item_price = Decimal(str(item_data['price']))
                item_quantity = int(item_data['quantity']) 
                item_total = item_price * item_quantity
                total_price += item_total
                
                order_items.append({
                    'article': article,
                    'table_name': table_name,
                    'price': item_price,
                    'quantity': item_quantity,
                    'total_price': item_total,
                    'brand_id': item_data.get('brand_id'),
                    'comment': item_data.get('comment', '')
                })

                # Додаємо інформацію для листа
                if table_name == 'stock':
                    delivery_time = _("In Stock")
                else:
                    cursor.execute("""
                        SELECT delivery_time FROM price_lists 
                        WHERE table_name = %s
                    """, (table_name,))
                    result = cursor.fetchone()
                    delivery_time_str = result['delivery_time'] if result else '7-14'
                    delivery_time = _("In Stock") if delivery_time_str == '0' else f"{delivery_time_str} {_('days')}"
                
                email_items.append({
                    'article': article,
                    'price': float(item_price),
                    'quantity': item_quantity,
                    'delivery_time': delivery_time
                })
        
        # Створюємо замовлення - ОНОВЛЕНО: пишемо needs_invoice та invoice_details
        cursor.execute("""
            INSERT INTO public_orders 
            (user_id, total_price, status, created_at, updated_at, delivery_address, needs_invoice, invoice_details, payment_status, shipping_method)
            VALUES (%s, %s, 'new', NOW(), NOW(), %s, %s, %s, 'unpaid', %s)
            RETURNING id
        """, (
            user_id,
            total_price,
            json.dumps(delivery_data, default=json_serial),
            needs_invoice,
            json.dumps(invoice_details, default=json_serial) if invoice_details else None,
            shipping_method
        ))
        
        order_id = cursor.fetchone()['id']
        
        # Додаємо деталі замовлення
        for item in order_items:
            cursor.execute("""
                INSERT INTO public_order_details 
                (order_id, article, table_name, price, quantity, total_price, comment, brand_id, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', NOW())
            """, (
                order_id,
                item['article'],
                item['table_name'],
                item['price'],
                item['quantity'],
                item['total_price'],
                item['comment'],
                item['brand_id']
            ))
        
        # Зберігаємо зміни до бази даних
        conn.commit()
        
        # Відправляємо лист з підтвердженням
        try:
            email_sent = send_email(
                to_email=email,
                subject=f"Order #{order_id}", 
                ordered_items=email_items,
                delivery_data=delivery_data, 
                lang=session.get('language', 'sk')
            )
            
            if not email_sent:
                # Додаємо замовлення до черги для відправки пізніше
                cursor.execute("""
                    INSERT INTO email_queue 
                    (recipient, subject, order_id, user_id, delivery_data, ordered_items, lang, created_at, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 'pending')
                """, (
                    email,
                    f"Order #{order_id}",
                    order_id,
                    user_id,
                    json.dumps(delivery_data, default=json_serial),
                    json.dumps(email_items, default=json_serial),
                    session.get('language', 'sk')
                ))
                conn.commit()
        except Exception as e:
            logging.error(f"Error sending confirmation email: {e}", exc_info=True)
        
        # Очищаємо кошик
        session['public_cart'] = {}
        session['cart_count'] = 0
        session.modified = True
        
        # Зберігаємо інформацію про замовлення для сторінки підтвердження
        session['guest_order'] = {
            'order_id': order_id,
            'items': email_items,
            'total_price': float(total_price),
            'delivery_data': delivery_data,
            'needs_invoice': needs_invoice,                # ДОДАНО
            'invoice_details': invoice_details,            # ДОДАНО
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        flash(_("Your order has been placed! Check your email for confirmation."), "success")
        # Рендеримо шаблон напряму замість редіректу
        return render_template(
            'public/orders/guest_confirmation.html',
            order=session['guest_order'],
            items=session['guest_order']['items']
        )
        
    except Exception as e:
        logging.error(f"Error in guest_checkout: {e}", exc_info=True)
        if 'conn' in locals():
            conn.rollback()
        flash(_("Error processing your order. Please try again."), "error")
        return redirect(url_for('public_cart'))
    
    finally:
        if 'conn' in locals():
            conn.close()





@app.route('/guest/order/confirmation')
def guest_order_confirmation():
    """Display confirmation page for guest orders"""
    # Get order info from session
    guest_order = session.get('guest_order')
    
    if not guest_order:
        flash(_("Order information not found."), "error")
        return redirect(url_for('index'))
    
    return render_template(
        'public/orders/guest_confirmation.html',
        order=guest_order,
        items=guest_order['items']
    )




# # Кількість товару в кошику користувача
def get_cart_count(user_id):
    """Повертає кількість товарів у кошику користувача"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(quantity), 0) 
            FROM cart 
            WHERE user_id = %s
        """, (user_id,))
        count = cursor.fetchone()[0]
        return int(count)
    except Exception as e:
        logging.error(f"Error getting cart count: {e}")
        return 0
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()




# Маршрут з префіксом мови
@app.route('/<lang>/product/<article>')
def localized_product_details(lang, article):
    """Сторінка товару з мовним префіксом"""
    # Перевіряємо, чи підтримується мова
    if lang not in app.config['BABEL_SUPPORTED_LOCALES']:
        # Якщо мова не підтримується, перенаправляємо на стандартну версію
        return redirect(url_for('product_details', article=article))
    
    # Зберігаємо мову в сесії
    session['language'] = lang
    session.modified = True
    
    # Очищаємо кеш сторінки товару для правильного відображення мови
    clear_page_cache_for_user()
    
    # Викликаємо стандартну функцію показу товару
    return product_details(article)

@app.route('/<lang>/')
def localized_index(lang):
    """Головна сторінка з мовним префіксом"""
    if lang not in app.config['BABEL_SUPPORTED_LOCALES']:
        return redirect(url_for('index'))
    
    session['language'] = lang
    session.modified = True
    clear_page_cache_for_user()
    
    return index()

@app.route('/<lang>/category/<slug>')
def localized_category(lang, slug):
    """Категорія з мовним префіксом"""
    if lang not in app.config['BABEL_SUPPORTED_LOCALES']:
        return redirect(url_for('view_category', slug=slug))
    
    session['language'] = lang
    session.modified = True
    clear_page_cache_for_user()
    
    return view_category(slug)

@app.after_request
def add_headers(response):
    # Додаємо заголовок для сторінок продуктів
    if '/product/' in request.path:
        response.headers['X-Robots-Tag'] = 'index, follow'
    
    # Додаємо заголовок для URL з токенами
    if re.search(r'/[0-9a-f]{32,}/', request.path, re.IGNORECASE):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    
    return response


@app.after_request
def add_indexing_header(response):
    if request.path.endswith('/product/') or '/product/' in request.path:
        response.headers['X-Robots-Tag'] = 'index, follow'
    return response

@app.after_request
def add_x_robots_tag(response):
    if '/product/' in request.path:
        response.headers['X-Robots-Tag'] = 'index, follow'
    return response


#Карточка товару
@app.route('/product/<article>')
@cache.cached(timeout=3600, key_prefix=make_lang_cache_key)
def product_details(article):
    try:
        # Нормалізуємо артикул для пошуку в базі
        normalized_article = normalize_article(article)
        
        
        # ДОДАЄМО ДЕТАЛЬНЕ ЛОГУВАННЯ
        logging.info(f"=== ARTICLE NORMALIZATION ===")
        logging.info(f"Original article: '{article}'")
        logging.info(f"Normalized article: '{normalized_article}'")
        logging.info(f"Original length: {len(article)}")
        logging.info(f"Normalized length: {len(normalized_article)}")
                
        with safe_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            # Отримуємо поточну мову
            lang = session.get('language', 'sk')

            logging.info(f"=== Starting product_details for original article: {article}, normalized: {normalized_article} ===")

            # Get stock info first - використовуємо нормалізований артикул
            cursor.execute("""
                SELECT s.article, s.price, s.brand_id, b.name as brand_name
                FROM stock s
                LEFT JOIN brands b ON s.brand_id = b.id
                WHERE s.article = %s
            """, (normalized_article,))
            stock_data = cursor.fetchone()
            logging.info(f"Stock data: {dict(stock_data) if stock_data else 'Not found'}")

            # Initialize product_data
            product_data = {
                'name': article,  # Показуємо оригінальний артикул
                'description': '',
                'photo_urls': [],
                'brand_name': stock_data['brand_name'] if stock_data else None,
                'brand_id': stock_data['brand_id'] if stock_data else None
            }
            
            # Отримуємо категорії товару - використовуємо нормалізований артикул
            cursor.execute("""
                SELECT c.*
                FROM product_categories pc
                JOIN categories c ON pc.category_id = c.id
                WHERE pc.article = %s
                ORDER BY c.parent_id NULLS FIRST, c.order_index
            """, (normalized_article,))
            product_categories = cursor.fetchall()

            # Get product info with language-specific fields - використовуємо нормалізований артикул
            cursor.execute(f"""
                SELECT 
                    article,
                    name_{lang} as name,
                    description_{lang} as description
                FROM products
                WHERE article = %s
            """, (normalized_article,))
            
            db_product = cursor.fetchone()
            if db_product:
                product_data['name'] = db_product['name'] or article  # Показуємо оригінальний
                product_data['description'] = db_product['description'] or ''

            # Отримуємо фотографії - використовуємо нормалізований артикул
            cursor.execute("""
                SELECT image_url 
                FROM product_images 
                WHERE product_article = %s 
                ORDER BY is_main DESC, id ASC
            """, (normalized_article,))
            product_data['photo_urls'] = [row['image_url'] for row in cursor.fetchall()]

            prices = []

            if stock_data:
                price_data = {
                    'table_name': 'stock',
                    'brand_name': stock_data['brand_name'],
                    'brand_id': stock_data['brand_id'],
                    'price': stock_data['price'],
                    'base_price': stock_data['price'],
                    'in_stock': True,
                    'delivery_time': _("In Stock")
                }
                prices.append(price_data)
                logging.info(f"Added stock price: {price_data}")

            # Get prices from price_lists - використовуємо нормалізований артикул
            cursor.execute("""
                SELECT pl.table_name, pl.brand_id, pl.delivery_time, b.name as brand_name 
                FROM price_lists pl
                LEFT JOIN brands b ON pl.brand_id = b.id
                WHERE pl.table_name != 'stock'
            """)
            tables = cursor.fetchall()

            price_found = False

            for table in tables:
                if table['table_name'] != 'stock':
                    table_name = table['table_name']
                    brand_id = table['brand_id']
                    brand_name = table['brand_name']
                    
                    cursor.execute(f"""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_name = %s
                        )
                    """, (table_name,))
                    
                    if cursor.fetchone()[0]:
                        cursor.execute(f"""
                            SELECT EXISTS (
                                SELECT FROM information_schema.columns 
                                WHERE table_name = %s AND column_name = 'brand_id'
                            )
                        """, (table_name,))
                        has_brand_id = cursor.fetchone()[0]
                        
                        if has_brand_id:
                            query = f"""
                                SELECT t.article, t.price, t.brand_id, b.name as brand_name
                                FROM {table_name} t
                                LEFT JOIN brands b ON t.brand_id = b.id
                                WHERE t.article = %s
                            """
                        else:
                            query = f"""
                                SELECT article, price
                                FROM {table_name}
                                WHERE article = %s
                            """
                        
                        cursor.execute(query, (normalized_article,))
                        result = cursor.fetchone()
                        
                        if result:
                            price_found = True
                            markup_percentage = get_markup_by_role('public')
                            base_price = result['price']
                            final_price = calculate_price(base_price, markup_percentage)

                            if has_brand_id and result.get('brand_name'):
                                actual_brand_name = result['brand_name']
                                actual_brand_id = result['brand_id']
                            else:
                                actual_brand_name = brand_name
                                actual_brand_id = brand_id

                            price_data = {
                                'table_name': table_name,
                                'brand_name': actual_brand_name,
                                'brand_id': actual_brand_id,
                                'price': final_price,
                                'base_price': base_price,
                                'in_stock': table['delivery_time'] == '0',
                                'delivery_time': (_("In Stock") if table['delivery_time'] == '0' 
                                                else f"{table['delivery_time']} {_('days')}")
                            }
                            prices.append(price_data)
                            logging.info(f"Added price from {table_name}: {price_data}")

            prices.sort(key=lambda x: float(x['price']))
            logging.info(f"Final prices count: {len(prices)}")

            price = prices[0] if prices else None
            
            if price and 'brand_name' in price:
                product_data['brand_name'] = price['brand_name']

            if not db_product and not stock_data and not price_found:
                return render_template(
                    'public/article_not_found.html',
                    article=article  # Показуємо оригінальний артикул
                )

            return render_template(
                'public/product_details.html',
                product_data=product_data,
                prices=prices,
                price=price,
                brand_name=product_data['brand_name'],
                article=article,  # Показуємо оригінальний артикул
                product_categories=product_categories
            )

    except Exception as e:
        logging.error(f"Error in product_details: {e}", exc_info=True)
        flash(_("An error occurred while processing your request."), "error")
        return redirect(url_for('index'))



# Управління фотографіями товарів
@app.route('/<token>/admin/photos/manage')
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_manage_photos(token):
    """Сторінка управління фотографіями товарів"""
    conn = None
    cursor = None
    
    try:
        # Параметри фільтру
        article_filter = request.args.get('article', '')
        source_filter = request.args.get('source', 'all')  # 'all', 'stock', 'enriched'
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Базовий запит для отримання товарів (виправлений)
        products_query = """
            SELECT DISTINCT pi.product_article as article, 
                           null as name, 
                           b.name as brand_name
            FROM product_images pi
            LEFT JOIN brands b ON 
                CASE 
                    WHEN LEFT(pi.product_article, 2) ~ '^[0-9]+$' 
                    THEN CAST(LEFT(pi.product_article, 2) AS INTEGER) = b.id
                    ELSE false
                END
        """
        
        # Додаємо умови фільтрації
        params = []
        where_conditions = []
        
        if article_filter:
            where_conditions.append("pi.product_article ILIKE %s")
            params.append(f"%{article_filter}%")
        
        # Додаємо умову для source_filter
        if source_filter == 'stock':
            where_conditions.append("pi.product_article IN (SELECT article FROM stock)")
        elif source_filter == 'enriched':
            where_conditions.append("""
                pi.product_article IN (
                    SELECT p.article FROM products p
                    UNION
                    SELECT pi2.product_article FROM product_images pi2
                )
                AND pi.product_article NOT IN (SELECT article FROM stock)
            """)
        
        # Додаємо WHERE якщо є умови
        if where_conditions:
            products_query += " WHERE " + " AND ".join(where_conditions)
        
        # Додаємо сортування
        products_query += " ORDER BY pi.product_article LIMIT 100"
        
        # Виконуємо запит для отримання товарів
        cursor.execute(products_query, params)
        products_data = cursor.fetchall()
        
        # Отримуємо фотографії для кожного товару
        products = []
        for product in products_data:
            article = product['article']
            
            try:
                # Запит на фото з сортуванням: спочатку головне, потім за sort_order
                cursor.execute("""
                    SELECT image_url, is_main, sort_order
                    FROM product_images
                    WHERE product_article = %s
                    ORDER BY is_main DESC, sort_order, image_url
                """, (article,))
                
                photos = [row['image_url'] for row in cursor.fetchall()]
                
                # Додаємо товар з фото до списку
                products.append({
                    'article': article,
                    'name': product['name'] if product['name'] else article,
                    'brand_name': product['brand_name'] if product['brand_name'] else 'Unknown',
                    'photos': photos
                })
            except Exception as inner_e:
                logging.error(f"Error fetching photos for article {article}: {inner_e}")
                # Пропускаємо цей товар, але не перериваємо всю операцію
                continue
        
        return render_template('admin/photos/manage_photos.html', 
                              products=products, 
                              article_filter=article_filter,
                              source_filter=source_filter,
                              token=token)
                              
    except Exception as e:
        logging.error(f"Error managing photos: {e}", exc_info=True)
        if conn:
            try:
                conn.rollback()  # Відкат транзакції у разі помилки
            except:
                pass
        flash(f"Помилка: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard', token=token))
    finally:
        # Гарантуємо закриття з'єднань
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass


# Завантаження нових фотографій
@app.route('/<token>/admin/photos/upload', methods=['GET', 'POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_upload_photos(token):
    """Сторінка завантаження фотографій товарів"""
    if request.method == 'POST':
        # Від самого початку ініціалізуємо змінні для обробки помилок
        error_messages = []
        success_count = 0
        conn = None
        cursor = None
        
        try:
            # Отримуємо артикул, для якого додаємо фото
            article = request.form.get('article', '').strip()
            
            if not article:
                flash("Необхідно вказати артикул", "danger")
                return redirect(url_for('admin_upload_photos', token=token))
            
            # Конвертуємо в верхній регістр для стабільного пошуку
            article = article.upper()
            
            # Перевіряємо наявність артикулу в базі
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Починаємо транзакцію
            conn.autocommit = False
            
            # Перевіряємо чи існує товар в будь-якій з таблиць
            cursor.execute("SELECT table_name FROM price_lists")
            tables = cursor.fetchall()
            
            product_exists = False
            
            # Для кожної таблиці прайс-листів
            for table_row in tables:
                table = table_row[0]
                try:
                    cursor.execute(f"SELECT 1 FROM \"{table}\" WHERE UPPER(article) = %s", (article,))
                    if cursor.fetchone():
                        product_exists = True
                        break
                except Exception as e:
                    logging.warning(f"Error checking article in table {table}: {e}")
            
            # Якщо товар не знайдено
            if not product_exists:
                conn.rollback()
                cursor.close()
                conn.close()
                flash(f"Товар з артикулом {article} не знайдено в жодній з таблиць", "danger")
                return redirect(url_for('admin_upload_photos', token=token))
            
            # Перевіряємо чи є в базі фото для цього товару
            cursor.execute("SELECT COUNT(*) FROM product_images WHERE UPPER(product_article) = %s", (article,))
            has_existing_photos = cursor.fetchone()[0] > 0
            
            # 1. Завантаження з URL
            if 'photo_urls' in request.form and request.form['photo_urls'].strip():
                urls = [url.strip() for url in request.form['photo_urls'].split('\n') if url.strip()]
                
                if not urls:
                    conn.rollback()
                    cursor.close()
                    conn.close()
                    flash("Не надано жодного URL фото", "danger")
                    return redirect(url_for('admin_upload_photos', token=token, article=article))
                
                for i, url in enumerate(urls):
                    try:
                        # Додаємо фото в БД
                        is_main = not has_existing_photos and i == 0  # Перше фото буде головним, якщо немає інших
                        sort_order = 0 if is_main else (i + 1)  # Головне фото має порядок 0, інші - по порядку
                        
                        # Перевіряємо, чи цього фото ще немає
                        cursor.execute(
                            "SELECT id FROM product_images WHERE UPPER(product_article) = %s AND image_url = %s", 
                            (article, url)
                        )
                        if cursor.fetchone():
                            error_messages.append(f"Фото вже існує: {url}")
                            continue
                        
                        # Додаємо нове фото
                        cursor.execute("""
                            INSERT INTO product_images (product_article, image_url, is_main, sort_order)
                            VALUES (%s, %s, %s, %s)
                        """, (article, url, is_main, sort_order))
                        
                        success_count += 1
                    except Exception as e:
                        error_messages.append(f"Помилка для URL {url}: {str(e)}")
            
            # 2. Завантаження файлів
            if 'photos' in request.files:
                uploaded_files = request.files.getlist('photos')
                valid_files = [f for f in uploaded_files if f and f.filename]
                
                if valid_files:
                    upload_temp_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_photos')
                    os.makedirs(upload_temp_dir, exist_ok=True)
                    
                    for i, file in enumerate(valid_files):
                        try:
                            if not allowed_file(file.filename):
                                error_messages.append(f"Недопустимий тип файлу: {file.filename}")
                                continue
                            
                            # Генеруємо безпечне ім'я файлу з артикулом на початку
                            filename = article + "_" + str(uuid.uuid4()) + "." + file.filename.rsplit('.', 1)[1].lower()
                            file_path = os.path.join(upload_temp_dir, filename)
                            file.save(file_path)
                            
                            # Завантажуємо на FTP
                            try:
                                image_url = upload_to_ftp(file_path, filename)
                                os.remove(file_path)  # Видаляємо тимчасовий файл
                                
                                # Додаємо в базу даних
                                is_main = not has_existing_photos and i == 0 and success_count == 0
                                sort_order = 0 if is_main else (success_count + i + 1)
                                
                                cursor.execute("""
                                    INSERT INTO product_images (product_article, image_url, is_main, sort_order)
                                    VALUES (%s, %s, %s, %s)
                                """, (article, image_url, is_main, sort_order))
                                
                                success_count += 1
                                
                            except Exception as upload_error:
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                                error_messages.append(f"Помилка завантаження {file.filename}: {str(upload_error)}")
                                
                        except Exception as file_error:
                            error_messages.append(f"Помилка обробки {file.filename}: {str(file_error)}")
            
            # Завершуємо транзакцію
            if success_count > 0:
                conn.commit()
                flash(f"Успішно завантажено {success_count} фото", "success")
            else:
                conn.rollback()
                flash("Жодне фото не було завантажено", "warning")
            
            for error in error_messages:
                flash(error, "danger")
                
            return redirect(url_for('admin_upload_photos', token=token, article=article))
                
        except Exception as e:
            logging.error(f"Error uploading photos: {e}", exc_info=True)
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            flash(f"Помилка: {str(e)}", "danger")
            return redirect(url_for('admin_upload_photos', token=token))
        finally:
            # Гарантуємо закриття з'єднання
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
    return render_template('admin/photos/upload_photos.html', token=token)


# Встановлення головного фото
@app.route('/<token>/admin/photos/set-main', methods=['POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_set_main_photo(token):
    """Встановлює головне фото для товару"""
    try:
        data = request.json
        article = data.get('article')
        image_url = data.get('image_url')
        
        if not article or not image_url:
            return jsonify({'success': False, 'message': 'Article and image URL are required'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Починаємо транзакцію
        conn.autocommit = False
        
        try:
            # Скидаємо всі фото як не головні
            cursor.execute("""
                UPDATE product_images
                SET is_main = FALSE, sort_order = 
                    CASE 
                        WHEN sort_order = 0 THEN 999
                        ELSE sort_order
                    END
                WHERE product_article = %s
            """, (article,))
            
            # Встановлюємо нове головне фото
            cursor.execute("""
                UPDATE product_images
                SET is_main = TRUE, sort_order = 0
                WHERE product_article = %s AND image_url = %s
            """, (article, image_url))
            
            conn.commit()
            return jsonify({'success': True})
        except Exception as inner_e:
            conn.rollback()
            logging.error(f"Error setting main photo: {inner_e}", exc_info=True)
            return jsonify({'success': False, 'message': str(inner_e)})
        finally:
            cursor.close()
            conn.close()
        
    except Exception as e:
        logging.error(f"Error in set main photo: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})

# Видалення фото
@app.route('/<token>/admin/photos/delete', methods=['POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_delete_photo(token):
    """Видаляє фото товару"""
    try:
        data = request.json
        article = data.get('article')
        image_url = data.get('image_url')
        
        if not article or not image_url:
            return jsonify({'success': False, 'message': 'Відсутні необхідні параметри'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Отримуємо інформацію про фото перед видаленням
        cursor.execute("""
            SELECT is_main FROM product_images 
            WHERE product_article = %s AND image_url = %s
        """, (article, image_url))
        
        photo_info = cursor.fetchone()
        was_main = photo_info and photo_info[0]
        
        # Видаляємо фото з БД
        cursor.execute("""
            DELETE FROM product_images 
            WHERE product_article = %s AND image_url = %s
        """, (article, image_url))
        
        # Якщо видалили головне фото, встановлюємо нове
        if was_main:
            cursor.execute("""
                UPDATE product_images 
                SET is_main = true, sort_order = 0
                WHERE product_article = %s
                ORDER BY sort_order, image_url
                LIMIT 1
            """, (article,))
        
        conn.commit()
        
        # Спробуємо видалити з FTP, але не зупиняємо процес при помилці
        try:
            # Отримуємо ім'я файлу з URL
            filename = os.path.basename(image_url)
            delete_from_ftp(filename)
        except Exception as ftp_error:
            logging.warning(f"Could not delete file from FTP: {ftp_error}")
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logging.error(f"Error deleting photo: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


def delete_from_ftp(filename):
    """Видаляє файл з FTP сервера"""
    try:
        # FTP налаштування
        FTP_HOST = os.environ.get('FTP_HOST')
        FTP_USER = os.environ.get('FTP_USER')
        FTP_PASS = os.environ.get('FTP_PASS')
        
        # Розділяємо хост і порт, якщо вони вказані разом
        match = re.match(r'^([^:]+)(?::(\d+))?$', FTP_HOST) if FTP_HOST else None
        if match:
            FTP_HOST = match.group(1)
            FTP_PORT = int(match.group(2)) if match.group(2) else 21
        else:
            FTP_PORT = 21
        
        # Перевіряємо наявність налаштувань
        if not FTP_HOST or not FTP_USER or not FTP_PASS:
            logging.error("FTP облікові дані не встановлені в змінних середовища")
            raise ValueError("FTP облікові дані не встановлені в змінних середовища")
        
        # Оновлений шлях до директорії на FTP сервері
        FTP_DIR = "sub/image/products/"
        
        logging.info(f"Підключення до FTP сервера: {FTP_HOST}:{FTP_PORT}")
        ftp = ftplib.FTP()
        ftp.connect(host=FTP_HOST, port=FTP_PORT, timeout=30)
        
        # Включаємо пасивний режим
        ftp.set_pasv(True)
        
        ftp.login(FTP_USER, FTP_PASS)
        logging.info("Успішний вхід на FTP сервер")
        
        # Видаляємо файл
        file_path = f"{FTP_DIR}{filename}"
        logging.info(f"Видалення файлу: {file_path}")
        ftp.delete(file_path)
        
        ftp.quit()
        logging.info(f"Файл успішно видалено з FTP: {file_path}")
        return True
    except ftplib.error_perm as e:
        if str(e).startswith('550'):  # Файл не знайдено
            logging.warning(f"Файл не знайдено на FTP: {FTP_DIR}{filename}")
            return True
        logging.error(f"FTP помилка доступу: {e}")
        raise
    except (socket.gaierror, ConnectionRefusedError) as e:
        logging.error(f"FTP помилка з'єднання: {e}")
        raise
    except Exception as e:
        logging.error(f"Помилка видалення файлу з FTP: {e}", exc_info=True)
        raise

# Зміна порядку фото
@app.route('/<token>/admin/photos/reorder', methods=['POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_reorder_photos(token):
    """Змінює порядок фото товару"""
    try:
        data = request.json
        article = data.get('article')
        photo_order = data.get('photo_order', [])  # Список URL в потрібному порядку
        
        if not article or not photo_order:
            return jsonify({'success': False, 'message': 'Відсутні необхідні параметри'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Оновлюємо порядок для кожного фото
        for index, image_url in enumerate(photo_order):
            # Головне фото завжди має sort_order = 0
            sort_order = index if index > 0 else 0
            
            cursor.execute("""
                UPDATE product_images 
                SET sort_order = %s, is_main = %s
                WHERE product_article = %s AND image_url = %s
            """, (sort_order, index == 0, article, image_url))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logging.error(f"Error reordering photos: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

# обробка фотографій товарів основне фото
@app.route('/<token>/admin/manage-photos', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def manage_photos(token):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            if request.method == 'POST':
                # Handle JSON requests for AJAX
                if request.is_json:
                    data = request.get_json()
                    article = data.get('article')
                    image_url = data.get('image_url')
                else:
                    article = request.form.get('article')
                    image_url = request.form.get('image_url')
                
                # Reset main photo flag
                cursor.execute("""
                    UPDATE product_images 
                    SET is_main = FALSE 
                    WHERE product_article = %s
                """, (article,))
                
                # Set new main photo
                cursor.execute("""
                    UPDATE product_images 
                    SET is_main = TRUE 
                    WHERE product_article = %s AND image_url = %s
                """, (article, image_url))
                
                conn.commit()
                
                # Return JSON response for AJAX requests
                if request.is_json:
                    return jsonify({'success': True})
                
                flash("Main photo updated successfully", "success")
                return redirect(url_for('manage_photos', token=token))
            
            # GET request - fetch photos
            cursor.execute("""
                SELECT 
                    s.article,
                    s.brand_id,
                    b.name as brand_name,
                    p.name_uk as name,
                    array_agg(pi.image_url ORDER BY pi.is_main DESC, pi.id) as photos
                FROM stock s
                LEFT JOIN brands b ON s.brand_id = b.id
                LEFT JOIN products p ON s.article = p.article
                LEFT JOIN product_images pi ON s.article = pi.product_article
                GROUP BY s.article, s.brand_id, b.name, p.name_uk
                ORDER BY s.article
            """)
            
            products = cursor.fetchall()
            
            return render_template(
                'admin/photos/manage_photos.html',
                products=products,
                token=token
            )
            
    except Exception as e:
        logging.error(f"Error in manage_photos: {e}")
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash("Error loading photos", "error")
        return redirect(url_for('admin_dashboard', token=token))


@app.route('/<token>/admin/google-feed/refresh/<int:setting_id>', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def refresh_google_feed(token, setting_id):
    """Manually refresh Google Feed"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Get the feed settings
            cursor.execute("""
                SELECT * FROM google_feed_settings WHERE id = %s
            """, (setting_id,))
            
            settings = cursor.fetchone()
            
            if not settings:
                flash("Feed configuration not found", "error")
                return redirect(url_for('manage_google_feed', token=token))
            
            # Force regenerate the feed
            language = settings['language']
            
            # Очистити кеш для цього feed
            cache_key = f'view//google-merchant-feed/{language}.xml'
            cache.delete(cache_key)
            
            flash(f"Feed for {language.upper()} has been refreshed", "success")
            
            # Redirect back to the feed settings page
            return redirect(url_for('manage_google_feed', token=token))
            
    except Exception as e:
        logging.error(f"Error refreshing Google feed: {e}")
        flash("Error refreshing feed", "error")
        return redirect(url_for('manage_google_feed', token=token))


@app.route('/<token>/admin/google-feed/refresh-all', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def refresh_all_feeds(token):
    """Manually refresh all Google Feeds"""
    try:
        invalidate_merchant_feeds()  # Використовуємо функцію, яку ми визначили вище
        flash("All feeds have been refreshed", "success")
    except Exception as e:
        logging.error(f"Error refreshing all feeds: {e}")
        flash("Error refreshing all feeds", "error")
    
    return redirect(url_for('manage_google_feed', token=token))

@scheduler.task('interval', id='refresh_google_feeds', minutes=360)
def scheduled_refresh_google_feeds():
    """Automatically refresh all Google Merchant Feeds every 360 minutes"""
    try:
        logging.info("Starting scheduled Google Merchant Feed refresh")
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Get all active feed configurations
            cursor.execute("""
                SELECT id, language FROM google_feed_settings 
                WHERE enabled = TRUE
            """)
            
            feeds = cursor.fetchall()
            
            # Clear cache for each feed to force regeneration
            for feed in feeds:
                language = feed['language']
                cache_key = f'view//google-merchant-feed/{language}.xml'
                cache.delete(cache_key)
                logging.info(f"Cleared cache for {language} feed")
        
        logging.info("Completed scheduled Google Merchant Feed refresh")
    except Exception as e:
        logging.error(f"Error in scheduled Google feed refresh: {e}", exc_info=True)


@app.route('/<token>/admin/google-feed/delete/<int:setting_id>', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def delete_google_feed(token, setting_id):
    """Delete Google Feed configuration"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Delete the feed configuration
            cursor.execute("""
                DELETE FROM google_feed_settings 
                WHERE id = %s
            """, (setting_id,))
            
            if cursor.rowcount > 0:
                conn.commit()
                flash("Feed configuration deleted successfully", "success")
            else:
                flash("Feed configuration not found", "error")
                
    except Exception as e:
        logging.error(f"Error deleting Google feed setting: {e}")
        flash("Error deleting feed configuration", "error")
        
    return redirect(url_for('manage_google_feed', token=token))

def generate_feed_item(item, lang, settings):
    """Генерує елемент товару для Google Merchant Feed"""
    try:
        # Отримуємо з'єднання з базою даних
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Додати категорію
        cursor.execute("""
            SELECT c.*
            FROM product_categories pc
            JOIN categories c ON pc.category_id = c.id
            WHERE pc.article = %s
            ORDER BY c.parent_id NULLS FIRST, c.order_index
        """, (item['article'],))
        categories = cursor.fetchall()
        
        google_category_id = None
        product_type = []
        
        # Шукаємо google_category_id та будуємо ієрархію категорій
        for cat in categories:
            if cat['google_category_id'] and not google_category_id:
                google_category_id = cat['google_category_id']
            
            cat_name = cat[f'name_{lang}'] or cat['name_en'] or cat['name_uk']
            if cat_name:
                product_type.append(cat_name)
        
        # Створюємо елемент feed
        feed_item = []
        feed_item.append(f"<item>")
        feed_item.append(f"<g:id>{item['article']}</g:id>")
        feed_item.append(f"<title>{html.escape(item['name'] or item['article'])}</title>")
        
        # Додаємо опис якщо він є
        if item['description']:
            description = item['description'][:5000]  # Обмеження довжини опису для Google
            feed_item.append(f"<description>{html.escape(description)}</description>")
        else:
            feed_item.append(f"<description>{html.escape(item['name'] or item['article'])}</description>")
        
        # Додаємо посилання на товар
        product_url = f"{settings['domain_url']}/product/{item['article']}?lang_code={lang}"
        feed_item.append(f"<link>{product_url}</link>")
        
        # Додаємо зображення
        if item['main_image_url']:
            feed_item.append(f"<g:image_link>{item['main_image_url']}</g:image_link>")
        
        # Додаємо додаткові зображення якщо вони є
        if item['additional_images'] and isinstance(item['additional_images'], list):
            for img_url in item['additional_images'][:10]:  # Google дозволяє до 10 додаткових зображень
                feed_item.append(f"<g:additional_image_link>{img_url}</g:additional_image_link>")
        
        # Додаємо інформацію про наявність
        availability = "in_stock" if item['quantity'] > 0 else "out_of_stock"
        feed_item.append(f"<g:availability>{availability}</g:availability>")
        
        # Додаємо ціну
        price = float(item['price'])
        feed_item.append(f"<g:price>{price:.2f} EUR</g:price>")
        
        # Додаємо бренд
        if item['brand_name']:
            feed_item.append(f"<g:brand>{html.escape(item['brand_name'])}</g:brand>")
        
        # Додаємо категорії до фіду
        if google_category_id:
            feed_item.append(f"<g:google_product_category>{google_category_id}</g:google_product_category>")
            
        if product_type:
            product_type_str = " > ".join(product_type)
            feed_item.append(f"<g:product_type>{html.escape(product_type_str)}</g:product_type>")
        
        # Закриваємо елемент
        feed_item.append("</item>")
        
        # Закриваємо з'єднання
        cursor.close()
        conn.close()
        
        # Повертаємо рядок з елементом
        return "\n".join(feed_item)
        
    except Exception as e:
        logging.error(f"Error generating feed item for article {item['article']}: {e}", exc_info=True)
        return ""



def upload_to_ftp(file_path, filename):
    """Завантажує файл на FTP сервер і повертає URL"""
    try:
        # FTP налаштування
        FTP_HOST = os.environ.get('FTP_HOST', '')
        FTP_USER = os.environ.get('FTP_USER', '')
        FTP_PASS = os.environ.get('FTP_PASS', '')
        FTP_DIR = "sub/image/products/"
        FTP_URL = os.environ.get('FTP_URL', 'https://image.autogroup.sk/products/')
        
        # Перевіряємо наявність обов'язкових налаштувань
        if not FTP_HOST or not FTP_USER or not FTP_PASS:
            raise ValueError("Відсутні обов'язкові налаштування FTP. Перевірте змінні середовища.")
        
        # Розділяємо хост і порт, якщо вони вказані разом
        if ':' in FTP_HOST:
            host_parts = FTP_HOST.split(':')
            FTP_HOST = host_parts[0]
            FTP_PORT = int(host_parts[1])
        else:
            FTP_PORT = 21
        
        # Підключення до FTP з кількома спробами
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                logging.info(f"FTP підключення, спроба {attempt+1}/{max_attempts}")
                ftp = ftplib.FTP(timeout=30)
                ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
                ftp.login(FTP_USER, FTP_PASS)
                
                # Переходимо в директорію
                try:
                    ftp.cwd(FTP_DIR)
                except ftplib.error_perm:
                    # Якщо директорії немає, створюємо її
                    ftp.mkd(FTP_DIR)
                    ftp.cwd(FTP_DIR)
                
                # Завантажуємо файл
                with open(file_path, 'rb') as file:
                    ftp.storbinary(f'STOR {filename}', file)
                
                # Закриваємо з'єднання
                ftp.quit()
                
                # Повертаємо URL
                return f"{FTP_URL}{filename}"
            
            except (socket.error, ftplib.error_temp) as e:
                logging.warning(f"Спроба підключення до FTP {attempt+1} не вдалася: {e}")
                if attempt == max_attempts - 1:
                    logging.error(f"Всі спроби підключення до FTP не вдалися.")
                    raise Exception(f"Не вдалося підключитися до FTP після {max_attempts} спроб: {e}")
                time.sleep(1)  # Чекаємо секунду перед повторною спробою
    
    except socket.error as e:
        logging.error(f"FTP помилка socket: {e}")
        raise Exception(f"FTP помилка socket: {e}")
    except ftplib.error_perm as e:
        logging.error(f"FTP помилка доступу: {e}")
        raise Exception(f"FTP помилка доступу: {e}")
    except Exception as e:
        logging.error(f"Помилка завантаження на FTP: {e}", exc_info=True)
        raise Exception(f"Помилка завантаження на FTP: {e}")


def allowed_file(filename):
    """Перевіряє, чи допустимий тип файлу"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS



@app.route('/google-merchant-feed/<language>.xml')
def google_merchant_feed(language):
    """Generate Google Merchant feed for specific language"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Get active feed settings for specific language
            cursor.execute("""
                SELECT gs.*, b.name as brand_name 
                FROM google_feed_settings gs
                LEFT JOIN brands b ON gs.brand_id = b.id
                WHERE gs.enabled = TRUE AND gs.language = %s
                ORDER BY gs.created_at DESC
                LIMIT 1
            """, (language,))
            settings = cursor.fetchone()
            
            if not settings:
                return "No active feed settings found for this language", 404

            # Get products from configured price list
            price_list = settings['price_list_id']
            markup_percentage = settings['markup_percentage'] or 0
            
            query = f"""
                SELECT 
                    p.article,
                    p.name_{language} as name,
                    p.description_{language} as description,
                    pl.price * (1 + %s/100) as price,
                    b.name as brand_name,
                    %s as google_category,
                    COALESCE(s.quantity, 0) as quantity,
                    (
                        SELECT image_url FROM product_images 
                        WHERE product_article = p.article AND is_main = TRUE
                        LIMIT 1
                    ) as main_image_url,
                    (
                        SELECT json_agg(image_url) FROM product_images 
                        WHERE product_article = p.article AND is_main = FALSE
                        LIMIT 10
                    ) as additional_images
                FROM {price_list} pl
                JOIN products p ON pl.article = p.article
                LEFT JOIN stock s ON pl.article = s.article
                LEFT JOIN brands b ON s.brand_id = b.id
                WHERE p.name_{language} IS NOT NULL
            """
            
            params = [markup_percentage, settings['category']]
            
            if settings['brand_id']:
                query += " AND s.brand_id = %s"
                params.append(settings['brand_id'])
            
            cursor.execute(query, params)
            products = cursor.fetchall()
            
            # Process JSON data for additional images
            for product in products:
                # Validate main image URL
                if product['main_image_url'] and not product['main_image_url'].startswith(('http://', 'https://')):
                    product['main_image_url'] = f"{request.host_url.rstrip('/')}/{product['main_image_url'].lstrip('/')}"
                
                # Process additional images
                if product['additional_images']:
                    if isinstance(product['additional_images'], str):
                        try:
                            product['additional_images'] = json.loads(product['additional_images'])
                        except (json.JSONDecodeError, TypeError):
                            product['additional_images'] = []
                    
                    # Make sure it's a list
                    if not isinstance(product['additional_images'], list):
                        product['additional_images'] = []
                    
                    # Filter out invalid image URLs and ensure full URLs
                    valid_images = []
                    for img_url in product['additional_images']:
                        if img_url and isinstance(img_url, str):
                            # Make sure URL has proper protocol
                            if not img_url.startswith(('http://', 'https://')):
                                img_url = f"{request.host_url.rstrip('/')}/{img_url.lstrip('/')}"
                            valid_images.append(img_url)
                    product['additional_images'] = valid_images
                else:
                    product['additional_images'] = []
            
            # Generate XML - використовуємо Response для коректного повернення XML
            from flask import Response
            xml_content = render_template(
                'feeds/google_merchant.xml',
                products=products,
                domain=request.host_url.rstrip('/'),
                language=language
            )

            # Set response headers
            download = request.args.get('download', False)
            if download:
                response = Response(xml_content, mimetype='application/xml')
                response.headers["Content-Disposition"] = f"attachment; filename=google_feed_{language}.xml"
                return response
            
            return Response(xml_content, mimetype='application/xml')

    except Exception as e:
        logging.error(f"Error generating feed: {e}")
        return "Error generating feed", 500
    

# Керування Google feed
@app.route('/<token>/admin/google-feed', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def manage_google_feed(token):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Get current settings with brand names
            cursor.execute("""
                SELECT gs.*, b.name as brand_name 
                FROM google_feed_settings gs
                LEFT JOIN brands b ON gs.brand_id = b.id
                ORDER BY gs.created_at DESC
            """)
            settings = cursor.fetchall()

            # Get brands list
            cursor.execute("SELECT id, name FROM brands ORDER BY name")
            brands = cursor.fetchall()
            # Add "All Brands" option at the beginning of the list
            brands = [(-1, "All Brands")] + list(brands)

            # Get price lists
            cursor.execute("SELECT table_name FROM price_lists")
            price_lists = cursor.fetchall()

            # Languages list
            languages = ['sk', 'en', 'pl']

            if request.method == 'POST':
                enabled = request.form.get('enabled') == 'on'
                category = request.form.get('category')
                brand_id = request.form.get('brand_id')
                language = request.form.get('language')
                price_list = request.form.get('price_list_id')
                markup = request.form.get('markup', '0')

                # Convert brand_id to None if "All Brands" is selected
                if brand_id == '-1':
                    brand_id = None

                cursor.execute("""
                    INSERT INTO google_feed_settings 
                    (enabled, category, brand_id, language, price_list_id, markup_percentage)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (enabled, category, brand_id, language, price_list, markup))

                conn.commit()
                flash("Feed configuration added successfully", "success")
                return redirect(url_for('manage_google_feed', token=token))

            return render_template('admin/google_feed/settings.html',
                                settings=settings,
                                brands=brands,
                                price_lists=price_lists,
                                languages=languages,
                                token=token)

    except Exception as e:
        logging.error(f"Error in manage_google_feed: {e}")
        flash("Error managing Google feed settings", "error")
        return redirect(url_for('admin_dashboard', token=token))




@app.route('/update_public_cart', methods=['POST'])
def update_public_cart():
    """Оновлює кількість товару в публічному кошику"""
    try:
        article = request.form.get('article')
        table_name = request.form.get('table_name')
        new_quantity = int(request.form.get('quantity', 1))
        
        logging.info(f"Updating cart for user: {session.get('username', 'guest')}")
        logging.info(f"Article: {article}, Table: {table_name}, New quantity: {new_quantity}")
        
        # Validate inputs
        if not article or not table_name:
            flash(_("Missing article information"), "error")
            return redirect(url_for('public_cart'))
        
        if new_quantity < 1:
            flash(_("Quantity must be at least 1"), "error")
            return redirect(url_for('public_cart'))
        
        user_id = session.get('user_id')
        
        if user_id:
            # Оновлення для зареєстрованого користувача
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            cursor.execute("""
                UPDATE cart
                SET quantity = %s
                WHERE user_id = %s AND article = %s AND table_name = %s
            """, (new_quantity, user_id, article, table_name))
            
            rows_updated = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            if rows_updated > 0:
                # ВИПРАВЛЕНО: Оновлюємо лічильник в сесії після оновлення в БД
                update_cart_count_in_session(user_id)
                flash(_("Cart updated successfully"), "success")
            else:
                flash(_("Item not found in cart"), "error")
        else:
            # Оновлення для незареєстрованого користувача (в сесії)
            cart = session.get('public_cart', {})
            
            if article in cart and table_name in cart[article]:
                cart[article][table_name]['quantity'] = new_quantity
                session['public_cart'] = cart
                session.modified = True
                
                # Оновлюємо лічильник товарів
                update_cart_count_in_session()
                
                flash(_("Cart updated successfully"), "success")
            else:
                flash(_("Item not found in cart"), "error")
        
        return redirect(url_for('public_cart'))
        
    except ValueError:
        flash(_("Invalid quantity"), "error")
        return redirect(url_for('public_cart'))
    except Exception as e:
        logging.error(f"Error updating cart: {e}", exc_info=True)
        flash(_("Error updating cart"), "error")
        return redirect(url_for('public_cart'))


# Видалення товару з кошика публічного користувача@app.route('/public_remove_from_cart', methods=['POST'])
@app.route('/public_remove_from_cart', methods=['POST'])
def public_remove_from_cart():
    """Видаляє товар з кошика користувача"""
    try:
        article = request.form.get('article')
        table_name = request.form.get('table_name')

        logging.info(f"Removing from cart: article={article}, table={table_name}")
        
        if not article or not table_name:
            flash(_("Missing article or table name"), "error")
            return redirect(url_for('public_cart'))
        
        user_id = session.get('user_id')
        
        if user_id:
            # Видаляємо товар з бази даних для авторизованого користувача
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM cart 
                WHERE user_id = %s AND article = %s AND table_name = %s
            """, (user_id, article, table_name))
            
            conn.commit()
            cursor.close()
            conn.close()
        else:
            # Видаляємо товар з сесії для неавторизованого користувача
            cart = session.get('public_cart', {})
            
            if article in cart and table_name in cart[article]:
                del cart[article][table_name]
                
                # Якщо для артикула не залишилось таблиць, видаляємо і сам артикул
                if not cart[article]:
                    del cart[article]
                    
                session['public_cart'] = cart
                session.modified = True
        
        # Оновлюємо лічильник товарів
        update_cart_count_in_session()
        
        flash(_("Item removed from cart"), "success")
        
    except Exception as e:
        logging.error(f"Error removing from cart: {e}", exc_info=True)
        flash(_("Error removing item from cart"), "error")
        
    finally:
        return redirect(url_for('public_cart'))


def update_cart_count_in_session(user_id=None):
    """Оновлює кількість товарів у кошику в сесії користувача"""
    try:
        user_id = user_id or session.get('user_id')
        
        if user_id:
            # Для авторизованих користувачів рахуємо з бази даних
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(SUM(quantity), 0) 
                FROM cart 
                WHERE user_id = %s
            """, (user_id,))
            count = cursor.fetchone()[0]
            session['cart_count'] = int(count or 0)
            cursor.close()
            conn.close()
            logging.info(f"Updated cart count from database for user {user_id}: {session.get('cart_count')}")
        else:
            # Для неавторизованих користувачів, рахуємо з сесії
            cart = session.get('public_cart', {})
            if not cart:
                session['cart_count'] = 0
                session.modified = True
                return 0
                
            total_count = 0
            for article_data in cart.values():
                if isinstance(article_data, dict):
                    for item_data in article_data.values():
                        if isinstance(item_data, dict):
                            total_count += item_data.get('quantity', 0)
            
            session['cart_count'] = total_count
            logging.info(f"Updated cart count from session: {total_count}")
        
        session.modified = True
    except Exception as e:
        logging.error(f"Error updating cart count in session: {e}", exc_info=True)


@app.route('/set_language/<lang>')
def set_language(lang):
    """Встановлює мову інтерфейсу та оновлює preferred_language користувача"""
    # Якщо вибрана українська, перенаправляємо на словацьку
    if lang == 'uk':
        lang = 'sk'
        
    if lang in app.config['BABEL_SUPPORTED_LOCALES']:
        session['language'] = lang
        
        # Якщо користувач авторизований, зберігаємо його вибір в БД
        if 'user_id' in session:
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE users SET preferred_language = %s 
                        WHERE id = %s
                    """, (lang, session['user_id']))
                    conn.commit()
                    logging.info(f"Updated preferred language for user {session['user_id']} to {lang}")
            except Exception as e:
                logging.error(f"Error updating preferred language: {e}")
        
        # ДОДАНО: Очищаємо кеш поточної сторінки для всіх мов
        clear_page_cache_for_user()
    
    # Перенаправляємо користувача на сторінку, з якої він прийшов
    return redirect(request.referrer or url_for('index'))

@app.before_request
def before_request():
    # Якщо користувач раніше використовував українську мову, змінюємо на словацьку
    if session.get('language') == 'uk':
        session['language'] = 'sk'
        session.modified = True
    
    g.locale = session.get('language', 'sk')  # Змінюємо стандартне значення на 'sk'

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
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise ValueError("SECRET_KEY environment variable must be set in production!")
app.secret_key = secret_key


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
# Оновлена функція отримання з'єднання з повторними спробами
def get_db_connection():
    """Створює пряме з'єднання з базою даних (без пулу)"""
    try:
        conn = psycopg2.connect(
            dsn=os.environ.get('DATABASE_URL'),
            sslmode="require",
            cursor_factory=psycopg2.extras.DictCursor
        )
        
        # Встановлюємо таймаут для запитів, щоб уникнути зависання
        with conn.cursor() as cursor:
            cursor.execute("SET statement_timeout = 10000")  # 10 секунд
            conn.commit()
            
        return conn
    except Exception as e:
        logging.error(f"Error connecting to database: {e}")
        raise

# Додайте цю функцію для роботи з контекстним менеджером
# Змініть клас DatabaseConnection
class DatabaseConnection:
    def __enter__(self):
        self.conn = get_db_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, 'conn') and self.conn:
            try:
                if not self.conn.closed:
                    self.conn.close()
            except:
                pass  # Ігноруємо помилки при закритті



# Функція для повернення з'єднання в пул
def release_db_connection(conn):
    """Закриває з'єднання з базою даних"""
    try:
        if conn and hasattr(conn, 'closed') and not conn.closed:
            conn.close()
    except Exception as e:
        logging.error(f"Error closing connection: {e}")



# функція націнки для користувачів
def calculate_price(base_price, markup_percentage):
    # Розрахунок кінцевої ціни з урахуванням націнки
    markup_multiplier = Decimal(1) + (Decimal(markup_percentage) / Decimal(100))
    return round(base_price * markup_multiplier, 2)



def get_markup_by_role(role_name):
    """
    Отримання націнки за роллю з бази даних.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT markup_percentage 
                FROM roles 
                WHERE name = %s
            """, (role_name,))
            result = cursor.fetchone()
            if result:
                return result[0]
            return 39.0  # Стандартна націнка, якщо роль не знайдена
    except Exception as e:
        logging.error(f"Error getting markup for role {role_name}: {e}")
        return 39.0  # Стандартна націнка у випадку помилки

@app.route('/favicon.ico')
def favicon():
    """Спеціальний маршрут для уникнення обробки favicon.ico як токена"""
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico', mimetype='image/vnd.microsoft.icon'
    )

# Покращена функція validate_token з детальним логуванням
def validate_token(token):
    """Перевірка валідності токена з розширеним логуванням"""
    logging.debug(f"==================== START TOKEN VALIDATION ====================")
    logging.debug(f"Validating token: {token}")
    logging.debug(f"Request path: {request.path}")
    logging.debug(f"Request endpoint: {request.endpoint}")
    logging.debug(f"Request referrer: {request.referrer}")
    
    # Перевірка, чи токен не є назвою публічного маршруту
    common_routes = ['favicon.ico', 'static', 'public', 'product', 'about']
    if token in common_routes:
        logging.debug(f"Token '{token}' is a common route name, skipping validation")
        return False
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
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
            logging.debug(f"Token valid. User ID: {result['user_id']}, Role: {result['role']}")
            logging.debug(f"==================== END TOKEN VALIDATION (SUCCESS) ====================")
            return result
        
        logging.debug(f"Token invalid. No matching record found for token: {token}")
        logging.debug(f"==================== END TOKEN VALIDATION (FAILED) ====================")
        return None
    
    except Exception as e:
        logging.error(f"Error validating token: {e}")
        logging.debug(f"==================== END TOKEN VALIDATION (ERROR) ====================")
        return None
    
    finally:
        if 'conn' in locals():
            conn.close()




# Головна сторінка за токеном
@app.route('/<token>/')
def token_index(token):
    user_data = validate_token(token)
    if not user_data:
        flash(_("Invalid token."), "error")
        return redirect(url_for('index'))  # Якщо токен недійсний, перенаправляємо на головну

    # Якщо токен валідний, зберігаємо роль і токен у сесії
    session['token'] = token
    session['role'] = user_data['role']
    return render_template('user/index.html', role=user_data['role'])


# Головна сторінка - сортування за ціною від високої до низької
@app.route('/')
def index():
    """Головна сторінка з товарами"""
    # Очищаємо накопичені повідомлення про невірний токен
    if '_flashes' in session:
        current_flashes = session.pop('_flashes')
        # Залишаємо тільки останнє повідомлення, якщо воно не про невірний токен
        filtered_flashes = [(cat, msg) for cat, msg in current_flashes
                          if 'Invalid token' not in msg]
        if filtered_flashes:
            session['_flashes'] = filtered_flashes
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 24  # 4x5 сітка
        brand_filter = request.args.get('brand', type=int)
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримання доступних брендів з товарів на складі
            cursor.execute("""
                SELECT DISTINCT b.id, b.name 
                FROM stock s
                JOIN brands b ON s.brand_id = b.id
                WHERE s.quantity > 0
                ORDER BY b.name
            """)
            brands = cursor.fetchall()
            
            # Базовий SQL-запит
            base_query = """
                SELECT 
                    s.article,
                    s.quantity,
                    s.price,
                    b.name as brand_name,
                    b.id as brand_id,
                    p.name_uk as name,
                    p.description_uk as description,
                    (
                        SELECT image_url 
                        FROM product_images pi 
                        WHERE pi.product_article = s.article 
                        ORDER BY is_main DESC, id ASC 
                        LIMIT 1
                    ) as image_url
                FROM stock s
                LEFT JOIN brands b ON s.brand_id = b.id
                LEFT JOIN products p ON s.article = p.article
                WHERE s.quantity > 0
            """
            
            # Додаємо фільтр за брендом, якщо вказано
            params = []
            if brand_filter:
                base_query += " AND s.brand_id = %s"
                params.append(brand_filter)
            
            # Спершу підрахуємо загальну кількість товарів
            count_query = f"SELECT COUNT(*) FROM ({base_query}) AS filtered_stock"
            cursor.execute(count_query, params)
            total_items = cursor.fetchone()[0]
            
            # Додаємо сортування та пагінацію
            base_query += " ORDER BY s.price DESC LIMIT %s OFFSET %s"
            params.extend([per_page, (page - 1) * per_page])
            
            # Виконуємо запит з товарами
            cursor.execute(base_query, params)
            products = cursor.fetchall()
            
            has_more = total_items > (page * per_page)

            return render_template(
                'public/index.html',
                products=products,
                brands=brands,
                page=page,
                has_more=has_more
            )

    except Exception as e:
        logging.error(f"Error in index: {e}")
        flash("Error loading products", "error")
        return render_template('public/index.html')
    
# Додавання товару в кошик публічного користувача
@app.route('/public_add_to_cart', methods=['POST'])
def public_add_to_cart():
    """Add items to the shopping cart for any user (registered or anonymous)"""
    try:
        original_article = request.form.get('article')
        article = normalize_article(original_article)  # Нормалізуємо артикул
        selected_price = request.form.get('selected_price')
        
        logging.debug(f"Adding to cart - Original: {original_article}, Normalized: {article}, Selected price: {selected_price}")

        if not article or not selected_price:
            flash(_("Missing required product information"), "error")
            logging.error(f"Missing article={article} or selected_price={selected_price}")
            return redirect(url_for('index'))
            
        # Parse the selected price value
        parts = selected_price.split(':')
        if len(parts) != 2:
            flash(_("Invalid price format"), "error")
            logging.error(f"Invalid price format: {selected_price}")
            return redirect(url_for('index'))
            
        table_name = parts[0]
        
        # Extract price and brand_id from the second part
        price_brand_parts = parts[1].split('|')
        price = price_brand_parts[0]
        brand_id = int(price_brand_parts[1]) if len(price_brand_parts) > 1 else None
        
        # Get quantity field name based on table_name
        quantity_field = f"quantity_{table_name}"
        quantity_value = request.form.get(quantity_field) or request.form.get('quantity', 1)
        quantity = int(quantity_value)
        
        logging.info(f"Adding to cart: article={article}, table={table_name}, price={price}, quantity={quantity}, brand_id={brand_id}")
        
        if quantity < 1:
            flash(_("Quantity must be at least 1"), "error")
            return redirect(url_for('product_details', article=original_article))
        
        user_id = session.get('user_id')
        
        if user_id:
            # Якщо користувач авторизований, додаємо товар в БД
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Перевірка, чи товар вже є в кошику
            cursor.execute("""
                SELECT id, quantity FROM cart
                WHERE user_id = %s AND article = %s AND table_name = %s
            """, (user_id, article, table_name))
            existing_cart_item = cursor.fetchone()
            
            if existing_cart_item:
                # Оновлюємо кількість товару
                new_quantity = existing_cart_item['quantity'] + quantity
                cursor.execute("""
                    UPDATE cart
                    SET quantity = %s
                    WHERE id = %s
                """, (new_quantity, existing_cart_item['id']))
            else:
                # Додаємо новий товар у кошик
                cursor.execute("""
                    INSERT INTO cart 
                    (user_id, article, table_name, base_price, final_price, quantity, comment, brand_id, added_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (user_id, article, table_name, float(price), float(price), quantity, request.form.get('comment', ''), brand_id))
            
            conn.commit()
            cursor.close()
            conn.close()
        else:
            # Якщо користувач не авторизований, додаємо товар у сесію
            if 'public_cart' not in session:
                session['public_cart'] = {}
                
            if article not in session['public_cart']:
                session['public_cart'][article] = {}
                
            session['public_cart'][article][table_name] = {
                'price': float(price),
                'quantity': quantity,
                'brand_id': brand_id,
                'comment': request.form.get('comment', '')
            }
            
            session.modified = True
        
        logging.info(f"Cart after adding: {session.get('public_cart')}")
        flash(_("Item added to cart"), "success")
        
        update_cart_count_in_session()
        
    except Exception as e:
        logging.error(f"Error adding to cart: {e}", exc_info=True)
        flash(_("Error adding item to cart"), "error")
        
    finally:
        # Повертаємо користувача на сторінку товару з оригінальним артикулом
        if 'original_article' in locals() and original_article:
            return redirect(url_for('product_details', article=original_article))
        else:
            return redirect(url_for('index'))



def get_public_cart_count():
    """Повертає кількість товарів у кошику публічного користувача"""
    cart = session.get('public_cart', {})
    total_count = 0
    for item in cart.values():
        if isinstance(item, dict):
            for sub_item in item.values():
                total_count += sub_item.get('quantity', 0)
        else:
            # Якщо елемент не є словником, ігноруємо його
            logging.warning(f"Ignoring non-dictionary cart item: {item}")
            continue
    return total_count



# Пошук для публічних користувачів
@app.route('/public_search', methods=['GET', 'POST'])
def public_search():
    """Простий пошук товару за артикулом з перенаправленням на сторінку товару"""
    if request.method == 'POST':
        # Отримуємо оригінальний артикул і нормалізуємо його
        original_article = request.form.get('article', '').strip()
        article = normalize_article(original_article)
        
        logging.info(f"Search query: '{original_article}' normalized to: '{article}'")
        
        if not article:
            logging.warning("Empty search query")
            flash(_("Please enter an article for search."), "warning")
            return redirect(url_for('index'))

        # Пряме перенаправлення на сторінку товару з нормалізованим артикулом
        logging.info(f"Redirecting to product details for normalized article: {article}")
        return redirect(url_for('product_details', article=article))

    # GET запити перенаправляємо на головну
    return redirect(url_for('index'))

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
@add_noindex_header
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
@add_noindex_header
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



@app.route('/<token>/admin/orders/<int:order_id>/update_status', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def update_order_item_status(token, order_id):
    conn = None  # Ініціалізуємо conn тут
    try:
        data = request.get_json()  # Отримуємо JSON з тіла запиту
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

            # Визначаємо загальний статус замовлення
            if counts[8] == total_items:  # Всі completed
                new_order_status = 'completed'
            elif counts[7] == total_items:  # Всі ready_pickup
                new_order_status = 'ready_pickup'
            elif counts[6] == total_items:  # Всі in_transit
                new_order_status = 'in_transit'
            elif counts[5] == total_items:  # Всі invoice_received
                new_order_status = 'invoice_received'
            elif counts[4] == total_items:  # Всі ordered_supplier
                new_order_status = 'ordered_supplier'
            elif counts[3] == total_items:  # Всі accepted
                new_order_status = 'accepted'
            elif counts[2] == total_items:  # Всі pending
                new_order_status = 'pending'
            elif counts[1] == total_items:  # Всі in_review
                new_order_status = 'in_review'
            elif counts[0] == total_items:  # Всі new
                new_order_status = 'new'
            else:
                new_order_status = 'in_progress'

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



def get_category_breadcrumbs(category_id, cursor):
    """
    Рекурсивно отримує всі батьківські категорії для заданого ID категорії.
    Повертає список категорій, починаючи з кореневої.
    """
    breadcrumbs = []
    
    # Отримуємо батьківську категорію
    cursor.execute("""
        SELECT id, slug, name_uk, name_en, name_sk, name_pl, parent_id, image_url 
        FROM categories 
        WHERE id = (
            SELECT parent_id 
            FROM categories 
            WHERE id = %s
        )
    """, (category_id,))
    
    parent = cursor.fetchone()
    
    # Якщо є батьківська категорія, отримуємо її breadcrumbs і додаємо її
    if parent:
        parent_breadcrumbs = get_category_breadcrumbs(parent['id'], cursor)
        breadcrumbs = parent_breadcrumbs + [parent]
    
    return breadcrumbs


@app.route('/category/<slug>')
@cache.cached(timeout=1800, key_prefix=make_lang_cache_key)  # 30 хвилин
def view_category(slug):
    try:
        # Отримуємо поточну мову
        lang = session.get('language', app.config['BABEL_DEFAULT_LOCALE'])
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо інформацію про категорію
            cursor.execute("""
                SELECT id, slug, name_uk, name_en, name_sk, name_pl, parent_id, image_url 
                FROM categories WHERE slug = %s
            """, (slug,))
            category = cursor.fetchone()
            
            if not category:
                flash(_("Category not found."), "error")
                return redirect(url_for('index'))
            
            # Отримуємо хлібні крихти (батьківські категорії)
            breadcrumbs = get_category_breadcrumbs(category['id'], cursor)
            breadcrumbs.append(category)
            
            # Отримуємо підкатегорії
            cursor.execute("""
                SELECT id, slug, name_uk, name_en, name_sk, name_pl 
                FROM categories WHERE parent_id = %s ORDER BY order_index
            """, (category['id'],))
            subcategories = cursor.fetchall()
            
            # Отримуємо список всіх ID категорій та підкатегорій
            category_ids = [category['id']]
            if subcategories:
                for subcat in subcategories:
                    category_ids.append(subcat['id'])
            
            # Параметри фільтрації та сортування
            sort = request.args.get('sort', 'name_asc')
            brand = request.args.get('brand')
            page = request.args.get('page', 1, type=int)
            per_page = 24  # Товарів на сторінку
            offset = (page - 1) * per_page
            
            # Формуємо умови для WHERE в залежності від фільтрів
            where_conditions = ["pc.category_id = ANY(%s)"]
            params = [category_ids]
            
            if brand:
                # Змінюємо умову з s.brand_name на b.name
                where_conditions.append("b.name = %s")
                params.append(brand)
            
            where_clause = " AND ".join(where_conditions)
            
            # Формуємо умови для ORDER BY в залежності від сортування
            if sort == 'name_desc':
                order_by = f"COALESCE(p.name_{lang}, p.name_en, p.name_uk, p.article) DESC"
            elif sort == 'price_asc':
                order_by = "s.price ASC"
            elif sort == 'price_desc':
                order_by = "s.price DESC"
            else:  # за замовчуванням name_asc
                order_by = f"COALESCE(p.name_{lang}, p.name_en, p.name_uk, p.article) ASC"
            
            # Підраховуємо загальну кількість товарів
            count_query = f"""
                SELECT COUNT(*) FROM product_categories pc 
                JOIN stock s ON pc.article = s.article 
                LEFT JOIN products p ON pc.article = p.article 
                LEFT JOIN brands b ON s.brand_id = b.id
                WHERE {where_clause}
            """
            cursor.execute(count_query, params)
            total_products = cursor.fetchone()[0]
            
            # Отримуємо товари з пагінацією
            # Отримуємо товари з пагінацією - ВИПРАВЛЕНИЙ ЗАПИТ
            query = f"""
                SELECT DISTINCT pc.article, 
                    COALESCE(p.name_{lang}, p.name_en, p.name_uk, p.article) as name,
                    s.price, 
                    b.name as brand_name, 
                    (
                        SELECT image_url FROM product_images 
                        WHERE product_article = pc.article 
                        ORDER BY is_main DESC, id ASC LIMIT 1
                    ) as image_url
                FROM product_categories pc 
                JOIN stock s ON pc.article = s.article 
                LEFT JOIN products p ON pc.article = p.article 
                LEFT JOIN brands b ON s.brand_id = b.id
                WHERE {where_clause}
                ORDER BY name {sort.endswith('desc') and 'DESC' or 'ASC'}
                LIMIT %s OFFSET %s
            """
            params.extend([per_page, offset])
            cursor.execute(query, params)
            products = cursor.fetchall()
            
            
            # Отримуємо список брендів для фільтрації - ВИПРАВЛЕНИЙ ЗАПИТ
            cursor.execute("""
                SELECT DISTINCT b.name as brand_name 
                FROM product_categories pc
                JOIN stock s ON pc.article = s.article
                JOIN brands b ON s.brand_id = b.id
                WHERE pc.category_id = ANY(%s)
                AND b.name IS NOT NULL
                AND b.name != ''
                ORDER BY b.name
            """, [category_ids])
            
            brands = cursor.fetchall()

            # Формуємо об'єкт пагінації
            pagination = {
                'page': page,
                'per_page': per_page,
                'total': total_products,
                'pages': (total_products + per_page - 1) // per_page
            }
            
            # Параметри для пагінації
            pagination_args = {}
            if brand:
                pagination_args['brand'] = brand
            if sort != 'name_asc':
                pagination_args['sort'] = sort
            
            return render_template(
                'public/category.html',
                category=category,
                subcategories=subcategories,
                breadcrumbs=breadcrumbs,
                products=products,
                brands=brands,
                total_products=total_products,
                pagination=pagination,
                pagination_args=pagination_args,
                sort=sort
            )
    
    except Exception as e:
        logging.error(f"Error in view_category: {e}", exc_info=True)
        flash(_("An error occurred while processing your request."), "error")
        return redirect(url_for('index'))



# Додайте в app.py:
@app.route('/car-service')
def car_service():
    return render_template('public/car_service.html')



#
@app.route('/<token>/admin/manage-price-lists', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def manage_price_lists(token):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cursor.execute("""
            SELECT 
                pl.id,
                pl.table_name,
                s.name as supplier_name,
                pl.delivery_time,
                pl.created_at,
                pl.last_updated,  
                pl.supplier_id
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



# видалення прайслистів в manage price lists
@app.route('/<token>/admin/delete-price-list/<int:price_list_id>', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def delete_price_list(token, price_list_id):
    """
    Видаляє прайс-лист повністю, незалежно від посилань на нього.
    - Видаляє запис з таблиці price_lists
    - Видаляє саму таблицю прайс-листа
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Отримуємо інформацію про прайс-лист
        cursor.execute("SELECT table_name FROM price_lists WHERE id = %s", (price_list_id,))
        price_list = cursor.fetchone()
        
        if not price_list:
            flash("Прайс-лист не знайдено", "error")
            return redirect(url_for('manage_price_lists', token=token))
        
        table_name = price_list['table_name']
        logging.info(f"Deleting price list: {table_name} (ID: {price_list_id})")
        
        # Перевіряємо, чи є посилання на цей прайс-лист в order_details
        cursor.execute("""
            SELECT COUNT(*) FROM order_details 
            WHERE table_name = %s
        """, (table_name,))
        references_count = cursor.fetchone()[0]
        
        if references_count > 0:
            logging.info(f"Price list {table_name} has {references_count} references in order_details, but we will delete it anyway")
        
        # Видаляємо запис з таблиці price_lists
        cursor.execute("DELETE FROM price_lists WHERE id = %s", (price_list_id,))
        
        # Перевіряємо, чи існує таблиця, перш ніж її видаляти
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (table_name,))
        table_exists = cursor.fetchone()[0]
        
        if table_exists:
            # Видаляємо саму таблицю прайс-листа
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            flash(f"Прайс-лист '{table_name}' та таблицю повністю видалено", "success")
        else:
            flash(f"Прайс-лист '{table_name}' видалено з реєстру, але таблиці з такою назвою не існувало", "warning")
        
        conn.commit()
        
    except Exception as e:
        logging.error(f"Error deleting price list: {e}", exc_info=True)
        conn.rollback()
        flash(f"Помилка при видаленні прайс-листа: {str(e)}", "error")
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('manage_price_lists', token=token))


@app.route('/<token>/admin/update-price-list-supplier', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def update_price_list_supplier(token):
    try:
        price_list_id = request.form.get('price_list_id')
        supplier_id = request.form.get('supplier_id')
        delivery_time = request.form.get('delivery_time')  # Додаємо отримання терміну доставки

        # Логуємо отримані дані
        logging.info(f"Updating price list ID: {price_list_id}, supplier_id: {supplier_id}, delivery_time: {delivery_time}")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE price_lists
                SET supplier_id = %s,
                    delivery_time = %s
                WHERE id = %s
            """, (supplier_id, delivery_time, price_list_id))
            conn.commit()

        flash("Постачальника та термін доставки успішно оновлено", "success")

    except Exception as e:
        logging.error(f"Error updating supplier and delivery time: {e}")
        flash("Помилка при оновленні постачальника та терміну доставки", "error")

    return redirect(url_for('manage_price_lists', token=token))


# Завантаження прайсу в Адмінці
@app.route('/<token>/admin/upload_price_list', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def upload_price_list(token):
    """
    Обробляє завантаження прайс-листу.
    - GET: Повертає сторінку завантаження.
    - POST: Обробляє завантаження файлу та записує дані в базу, включаючи brand_id.
    """
    if request.method == 'GET':
        try:
            logging.info(f"Accessing upload page for token: {token}")
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо список прайс-листів
            cursor.execute("SELECT table_name FROM price_lists;")
            price_lists = cursor.fetchall()

            # Отримуємо список брендів для вибору
            cursor.execute("SELECT id, name FROM brands ORDER BY name;")
            brands = cursor.fetchall()
            
            # Отримуємо розширену інформацію про прайс-листи для відображення в таблиці
            cursor.execute("""
                SELECT 
                    pl.id,
                    pl.table_name,
                    s.name as supplier_name,
                    pl.delivery_time,
                    pl.created_at,
                    pl.last_updated,
                    pl.supplier_id
                FROM price_lists pl
                LEFT JOIN suppliers s ON pl.supplier_id = s.id
                ORDER BY pl.created_at DESC
            """)
            price_lists_info = cursor.fetchall()

            conn.close()
            
            return render_template(
                'admin/price_lists/upload_price_list.html', 
                price_lists=price_lists,
                price_lists_info=price_lists_info,
                brands=brands, 
                token=token
            )
            
        except Exception as e:
            logging.error(f"Error during GET request: {e}")
            flash("Error loading the upload page.", "error")
            return redirect(url_for('admin_dashboard', token=token))

    if request.method == 'POST':
        
        conn = None
        cursor = None
        # Зберігаємо поточний рівень логування
        current_log_level = logging.getLogger().level
        
        try:
            logging.info(f"Starting file upload for token: {token}")
            start_time = time.time()

            # Отримання параметрів форми
            table_name = request.form['table_name']
            new_table_name = request.form.get('new_table_name', '').strip()
            brand_id = request.form.get('brand_id')  # Отримання brand_id
            file = request.files.get('file')

            # Базове логування вхідних даних
            logging.info(f"Processing file upload: table_name={table_name}, new_table_name={new_table_name}, brand_id={brand_id}")

            if not file or file.filename == '':
                flash("No file uploaded or selected.", "error")
                return redirect(url_for('upload_price_list', token=token))

            # Встановлюємо вищий рівень логування під час обробки файлу (тільки ERROR і вище)
            logging.getLogger().setLevel(logging.ERROR)
            
            # Збільшуємо максимальний розмір поля для CSV-читача
            csv.field_size_limit(sys.maxsize)
            
            # Змінюємо підхід для обробки файлу залежно від розширення
            filename = file.filename.lower()
            logging.info(f"Processing file: {filename}")
            
            data = []  # Тут зберігатимемо дані для завантаження
            
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                # Обробка Excel файлу
                logging.info("Detected Excel file format")
                df = pd.read_excel(file)
                # Переконуємося, що у нас є правильні стовпці
                if len(df.columns) >= 2:
                    # Приводимо назви стовпців до нижнього регістру
                    df.columns = [str(col).lower() for col in df.columns]
                    # Шукаємо стовпці з артикулом і ціною
                    article_col = None
                    price_col = None
                    
                    # Відповідність можливих назв стовпців
                    article_names = ['article', 'артикул', 'код', 'code', 'номер', 'number']
                    price_names = ['price', 'ціна', 'цена', 'price', 'cost', 'вартість']
                    
                    for col in df.columns:
                        if article_col is None and any(name in col.lower() for name in article_names):
                            article_col = col
                        if price_col is None and any(name in col.lower() for name in price_names):
                            price_col = col
                    
                    # Якщо не знайдено, використовуємо перші два стовпці
                    if article_col is None:
                        article_col = df.columns[0]
                    if price_col is None:
                        price_col = df.columns[1]
                    
                    logging.info(f"Using columns: article_col={article_col}, price_col={price_col}")
                    logging.info(f"Processing {len(df)} rows from Excel file")
                    
                    # Обробляємо дані
                    for _, row in df.iterrows():
                        try:
                            article = str(row[article_col]).strip().upper()
                            price_str = str(row[price_col]).replace(',', '.')
                            price = float(price_str)
                            if article and price > 0:
                                data.append((article, price))
                        except Exception:
                            # Пропускаємо некоректні рядки
                            continue
                else:
                    logging.warning(f"Invalid Excel format: only {len(df.columns)} columns found")
                        
            else:
                # Обробка CSV/TXT файлу
                logging.info("Detected CSV/TXT file format")
                file_content = file.read().decode('utf-8', errors='ignore')
                
                # Визначаємо розділювач
                delimiters = [',', ';', '\t']
                delimiter = max(delimiters, key=lambda d: file_content.count(d))
                logging.info(f"Detected delimiter: '{delimiter}'")
                
                # Читаємо рядки
                lines = file_content.strip().split('\n')
                total_lines = len(lines)
                logging.info(f"Total lines in file: {total_lines}")
                
                # Пропускаємо заголовок
                processed_lines = 0
                for line_index, line in enumerate(lines):
                    if line_index == 0 and any(c.isalpha() for c in line):
                        continue
                    
                    parts = line.split(delimiter)
                    if len(parts) >= 2:
                        try:
                            article = parts[0].strip().replace(" ", "").upper()
                            price_str = parts[1].strip().replace(',', '.')
                            price = float(price_str)
                            if article and price > 0:
                                data.append((article, price))
                                processed_lines += 1
                        except Exception:
                            # Пропускаємо некоректні рядки
                            continue
                
                logging.info(f"Successfully processed {processed_lines} out of {total_lines} lines")

            # Відновлюємо рівень логування для виводу інформації
            logging.getLogger().setLevel(current_log_level)
            
            # Логування кількості успішно оброблених рядків
            valid_rows = len(data)
            logging.info(f"Total valid rows extracted: {valid_rows}")
            
            if valid_rows == 0:
                flash("No valid data found in file.", "error")
                return redirect(url_for('upload_price_list', token=token))

            # Підключення до бази даних
            conn = get_db_connection()
            cursor = conn.cursor()

            # Логіка для створення нової таблиці
            if table_name == 'new':
                if not new_table_name:
                    flash("New table name is required.", "error")
                    return redirect(url_for('upload_price_list', token=token))

                table_name = new_table_name.strip().replace(" ", "_").lower()
                if not re.match(r'^[a-z_][a-z0-9_]*$', table_name):
                    flash("Invalid table name. Only lowercase letters, numbers, and underscores are allowed.", "error")
                    return redirect(url_for('upload_price_list', token=token))

                try:
                    # Створюємо нову таблицю без brand_id в структурі
                    cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            article TEXT PRIMARY KEY,
                            price NUMERIC
                        );
                    """)
                    # Додаємо запис в price_lists з brand_id
                    cursor.execute("""
                        INSERT INTO price_lists (table_name, brand_id, created_at) 
                        VALUES (%s, %s, NOW())
                    """, (table_name, brand_id))
                    
                    conn.commit()
                    logging.info(f"Created new price list table: {table_name}")
                except Exception as e:
                    logging.error(f"Error creating new table: {e}")
                    flash("Error creating new table. Please check the table name and try again.", "error")
                    return redirect(url_for('upload_price_list', token=token))

            # Перевірка існування таблиці
            try:
                cursor.execute(f"SELECT 1 FROM information_schema.tables WHERE table_name = %s;", (table_name,))
                if cursor.fetchone() is None:
                    flash(f"Table '{table_name}' does not exist. Please try again.", "error")
                    return redirect(url_for('upload_price_list', token=token))
            except Exception as e:
                logging.error(f"Error checking table existence: {e}")
                flash("An error occurred while verifying the table. Please try again.", "error")
                return redirect(url_for('upload_price_list', token=token))

            # Очищення таблиці
            cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY;")
            conn.commit()
            logging.info(f"Truncated table: {table_name}")

            # Завантаження даних пакетами для підвищення продуктивності
            batch_size = 5000
            total_batches = (len(data) + batch_size - 1) // batch_size
            
            logging.info(f"Starting data upload: {valid_rows} rows in {total_batches} batches")
            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(data))
                batch = data[start_idx:end_idx]
                current_batch_size = len(batch)
                
                # Використовуємо execute_values для пакетного додавання (швидше ніж COPY)
                psycopg2.extras.execute_values(
                    cursor,
                    f"INSERT INTO {table_name} (article, price) VALUES %s ON CONFLICT (article) DO UPDATE SET price = EXCLUDED.price",
                    [(a, p) for a, p in batch],
                    template="(%s, %s)",
                    page_size=1000
                )
                conn.commit()
                logging.info(f"Batch {batch_num+1}/{total_batches}: Inserted {current_batch_size} rows")
            
            # Оновлюємо brand_id та last_updated в price_lists
            try:
                cursor.execute("""
                    UPDATE price_lists 
                    SET brand_id = %s,
                        last_updated = NOW()
                    WHERE table_name = %s
                """, (brand_id, table_name))
                conn.commit()
                logging.info(f"Updated brand_id={brand_id} and last_updated for price_list: {table_name}")
            except Exception as update_error:
                logging.warning(f"Could not update price_lists metadata: {update_error}")
                # Продовжуємо виконання, оскільки дані вже завантажені успішно
            
            execution_time = time.time() - start_time
            execution_time_formatted = f"{execution_time:.2f}"
            
            # Детальний лог з інформацією про результати
            logging.info(f"Price list upload complete: {valid_rows} rows imported to '{table_name}' in {execution_time_formatted} seconds")
            
            # Інформативне повідомлення для користувача
            upload_info = f"Uploaded {valid_rows} items to '{table_name}' in {execution_time_formatted} seconds"
            flash(upload_info, "success")
            
            return redirect(url_for('upload_price_list', token=token))

        except Exception as e:
            logging.error(f"Error during price list upload: {e}", exc_info=True)
            flash(f"An error occurred during upload: {str(e)}", "error")
            if conn:
                conn.rollback()
            return redirect(url_for('upload_price_list', token=token))
            
        finally:
            # Відновлюємо початковий рівень логування
            logging.getLogger().setLevel(current_log_level)
            
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                logging.info("Database connection closed")



def invalidate_merchant_feeds():
    """Очищає кеш для всіх Google Merchant feeds"""
    try:
        languages = ['sk', 'en', 'pl']
        for lang in languages:
            cache_key = f'view//google-merchant-feed/{lang}.xml'
            cache.delete(cache_key)
            logging.info(f"Cleared cache for {lang} merchant feed")
        return True
    except Exception as e:
        logging.error(f"Error invalidating merchant feeds cache: {e}")
        return False


@app.route('/<token>/admin/add-brand', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def add_brand(token):
    """Додає новий бренд до бази даних"""
    try:
        brand_name = request.form.get('brand_name')
        if not brand_name:
            flash("Brand name is required", "error")
            return redirect(url_for('upload_price_list', token=token))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Перевірка, чи вже існує бренд з таким іменем
            cursor.execute("SELECT id FROM brands WHERE name = %s", (brand_name,))
            existing_brand = cursor.fetchone()
            
            if existing_brand:
                flash(f"Brand '{brand_name}' already exists", "warning")
            else:
                # Спочатку отримуємо максимальне значення id
                cursor.execute("SELECT MAX(id) FROM brands")
                max_id = cursor.fetchone()[0] or 0
                
                # Синхронізуємо послідовність з поточним максимальним значенням
                cursor.execute("SELECT setval('brands_id_seq', %s)", (max_id,))
                
                # Потім виконуємо вставку
                cursor.execute(
                    "INSERT INTO brands (name) VALUES (%s)", 
                    (brand_name,)
                )
                conn.commit()
                
                # Отримуємо id нового бренду для логування
                cursor.execute("SELECT id FROM brands WHERE name = %s", (brand_name,))
                new_id = cursor.fetchone()[0]
                flash(f"New brand '{brand_name}' (ID: {new_id}) added successfully", "success")
                logging.info(f"New brand created: {brand_name} (ID: {new_id})")
                
        return redirect(url_for('upload_price_list', token=token))
        
    except Exception as e:
        logging.error(f"Error adding new brand: {e}", exc_info=True)
        flash(f"Error adding new brand: {str(e)}", "error")
        return redirect(url_for('upload_price_list', token=token))

# Оновлення та керування stock
@app.route('/<token>/admin/manage-stock', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def manage_stock(token):
    """Сторінка управління складом"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо дані зі стоку з назвами брендів
            cursor.execute("""
                SELECT s.article, s.quantity, s.price, s.brand_id, b.name as brand_name 
                FROM stock s
                LEFT JOIN brands b ON s.brand_id = b.id
                ORDER BY s.article
            """)
            stock_items = cursor.fetchall()
            
            # Отримуємо список брендів для форми
            cursor.execute("SELECT id, name FROM brands ORDER BY name")
            brands = cursor.fetchall()
            
            return render_template(
                'admin/stock/manage_stock.html',
                stock_items=stock_items,
                brands=brands,
                token=token
            )
            
    except Exception as e:
        logging.error(f"Error in manage_stock: {e}")
        flash("Error loading stock data", "error")
        return redirect(url_for('admin_dashboard', token=token))

# Робота зі stock
@app.route('/<token>/admin/stock/upload', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def upload_stock(token):
    """Завантаження Excel файлу зі стоком"""
    try:
        file = request.files.get('file')
        if not file:
            flash("No file uploaded", "error")
            return redirect(url_for('manage_stock', token=token))

        # Читаємо Excel файл
        df = pd.read_excel(file)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Додаємо кожен рядок в базу
            for _, row in df.iterrows():
                cursor.execute("""
                    INSERT INTO stock (article, quantity, price, brand_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (article) 
                    DO UPDATE SET
                        quantity = stock.quantity + EXCLUDED.quantity,
                        price = EXCLUDED.price,
                        brand_id = EXCLUDED.brand_id
                """, (
                    str(row['Артикуль']).strip().upper(),
                    int(row['кть']),
                    float(str(row['Ціна']).replace(',', '.')),
                    int(row['id бренду'])
                ))
            
            conn.commit()
            flash(f"Successfully uploaded {len(df)} items", "success")
            
    except Exception as e:
        logging.error(f"Error in upload_stock: {e}")
        flash(f"Error uploading file: {str(e)}", "error")
        
    return redirect(url_for('manage_stock', token=token))

# Робота зі stock
@app.route('/<token>/admin/stock/add', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def add_stock_item(token):
    """Додавання одного товару"""
    try:
        article = request.form.get('article').strip().upper()
        quantity = int(request.form.get('quantity'))
        price = float(request.form.get('price').replace(',', '.'))
        brand_id = int(request.form.get('brand_id'))
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO stock (article, quantity, price, brand_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (article) 
                DO UPDATE SET
                    quantity = stock.quantity + EXCLUDED.quantity,
                    price = EXCLUDED.price,
                    brand_id = EXCLUDED.brand_id
            """, (article, quantity, price, brand_id))
            conn.commit()
            
        flash(f"Successfully added/updated article {article}", "success")
        
    except Exception as e:
        logging.error(f"Error in add_stock_item: {e}")
        flash(f"Error adding item: {str(e)}", "error")
        
    return redirect(url_for('manage_stock', token=token))

# Робота зі stock
@app.route('/<token>/admin/stock/update/<article>', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def update_stock_item(token, article):
    """Оновлення існуючого товару"""
    try:
        quantity = int(request.form.get('quantity'))
        price = float(request.form.get('price').replace(',', '.'))
        brand_id = int(request.form.get('brand_id'))
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE stock 
                SET quantity = %s, price = %s, brand_id = %s
                WHERE article = %s
            """, (quantity, price, brand_id, article))
            conn.commit()
            
        flash(f"Successfully updated article {article}", "success")
        
    except Exception as e:
        logging.error(f"Error in update_stock_item: {e}")
        flash(f"Error updating item: {str(e)}", "error")
        
    return redirect(url_for('manage_stock', token=token))

# Робота зі stock
@app.route('/<token>/admin/stock/delete/<article>', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def delete_stock_item(token, article):
    """Видалення товару"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stock WHERE article = %s", (article,))
            conn.commit()
            
        flash(f"Successfully deleted article {article}", "success")
        
    except Exception as e:
        logging.error(f"Error in delete_stock_item: {e}")
        flash(f"Error deleting item: {str(e)}", "error")
        
    return redirect(url_for('manage_stock', token=token))

# Робота зі stock
@app.route('/<token>/admin/stock/clear', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def clear_stock(token):
    """Очищення всього стоку"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("TRUNCATE TABLE stock")
            conn.commit()
            
        flash("Successfully cleared all stock", "success")
        
    except Exception as e:
        logging.error(f"Error in clear_stock: {e}")
        flash(f"Error clearing stock: {str(e)}", "error")
        
    return redirect(url_for('manage_stock', token=token))




def handle_accept_name_change(invoice_detail_id, conn, cursor):
    """
    Обробляє прийняття зміни назви артикула.
    """
    try:
        # Отримуємо інформацію про позицію інвойсу
        cursor.execute("""
            SELECT 
                id.article,
                sod.order_details_id
            FROM invoice_details id
            JOIN supplier_order_details sod ON id.tracking_code = sod.tracking_code
            WHERE id.id = %s
        """, (invoice_detail_id,))
        
        item = cursor.fetchone()
        
        if not item:
            logging.error(f"Item not found for invoice_detail_id: {invoice_detail_id}")
            return False

        # Оновлюємо артикул в order_details
        cursor.execute("""
            UPDATE order_details 
            SET article = %s
            WHERE id = %s
        """, (item['article'], item['order_details_id']))
        logging.info(f"Updated order_details article for id: {item['order_details_id']} to {item['article']}")

        # Оновлюємо статус деталі інвойсу
        cursor.execute("""
            UPDATE invoice_details 
            SET status = 'processed',
                processed_at = NOW()
            WHERE id = %s
        """, (invoice_detail_id,))
        logging.info(f"Updated invoice_detail status for id: {invoice_detail_id}")

        return True

    except Exception as e:
        logging.error(f"Error handling wrong article: {e}", exc_info=True)
        return False


def handle_excess_quantity(invoice_detail_id, conn, cursor):
    """
    Обробляє ситуацію, коли кількість в інвойсі більша за кількість в замовленні.
    """
    try:
        # Отримуємо інформацію про позицію інвойсу
        cursor.execute("""
            SELECT 
                id.article,
                id.quantity as invoice_quantity,
                sod.order_details_id,
                od.quantity as order_quantity
            FROM invoice_details id
            JOIN supplier_order_details sod ON id.tracking_code = sod.tracking_code
            JOIN order_details od ON sod.order_details_id = od.id
            WHERE id.id = %s
        """, (invoice_detail_id,))
        item = cursor.fetchone()

        if not item:
            logging.error(f"Item not found for invoice_detail_id: {invoice_detail_id}")
            return False

        # Розраховуємо надлишкову кількість
        excess_quantity = item['invoice_quantity'] - item['order_quantity']

        if excess_quantity <= 0:
            logging.warning(f"No excess quantity for invoice_detail_id: {invoice_detail_id}")
            return False

        # Створюємо новий запис order_details для надлишку
        cursor.execute("""
            INSERT INTO order_details 
            (order_id, article, table_name, price, quantity)
            SELECT order_id, article, table_name, price, %s
            FROM order_details
            WHERE id = %s
        """, (excess_quantity, item['order_details_id']))

        # Оновлюємо статус деталі інвойсу
        cursor.execute("""
            UPDATE invoice_details 
            SET status = 'processed'
            WHERE id = %s
        """, (invoice_detail_id,))

        return True

    except Exception as e:
        logging.error(f"Error handling excess quantity: {e}", exc_info=True)
        return False


def handle_missing_quantity(invoice_detail_id, conn, cursor):
    """
    Обробляє ситуацію, коли кількість в інвойсі менша за кількість в замовленні.
    """
    try:
        # Отримуємо інформацію про позицію інвойсу
        cursor.execute("""
            SELECT 
                id.article,
                id.quantity as invoice_quantity,
                sod.order_details_id,
                od.quantity as order_quantity
            FROM invoice_details id
            JOIN supplier_order_details sod ON id.tracking_code = sod.tracking_code
            JOIN order_details od ON sod.order_details_id = od.id
            WHERE id.id = %s
        """, (invoice_detail_id,))
        item = cursor.fetchone()

        if not item:
            logging.error(f"Item not found for invoice_detail_id: {invoice_detail_id}")
            return False

        # Розраховуємо залишок кількості
        remaining_quantity = item['order_quantity'] - item['invoice_quantity']

        if remaining_quantity <= 0:
            logging.warning(f"No remaining quantity for invoice_detail_id: {invoice_detail_id}")
            return False

        # Оновлюємо кількість в поточному записі order_details
        cursor.execute("""
            UPDATE order_details 
            SET quantity = %s
            WHERE id = %s
        """, (item['invoice_quantity'], item['order_details_id']))

        # Створюємо новий запис order_details для залишку
        cursor.execute("""
            INSERT INTO order_details 
            (order_id, article, table_name, price, quantity)
            SELECT order_id, article, table_name, price, %s
            FROM order_details
            WHERE id = %s
        """, (remaining_quantity, item['order_details_id']))

        # Оновлюємо статус деталі інвойсу
        cursor.execute("""
            UPDATE invoice_details 
            SET status = 'processed'
            WHERE id = %s
        """, (invoice_detail_id,))

        return True

    except Exception as e:
        logging.error(f"Error handling missing quantity: {e}", exc_info=True)
        return False


def handle_price_mismatch(invoice_detail_id, action, conn, cursor):
    """Обробляє невідповідність ціни в інвойсі з урахуванням націнки клієнта."""
    try:
        logging.info(f"Processing price mismatch for invoice_detail_id: {invoice_detail_id}")

        # Отримуємо інформацію про позицію інвойсу та замовлення
        cursor.execute("""
            SELECT 
                id.price as invoice_price,
                sod.order_details_id,
                od.price as order_price,
                od.base_price as old_base_price,
                o.user_id,
                o.id as order_id
            FROM invoice_details id
            JOIN supplier_order_details sod ON id.tracking_code = sod.tracking_code
            JOIN order_details od ON sod.order_details_id = od.id
            JOIN orders o ON od.order_id = o.id
            WHERE id.id = %s
        """, (invoice_detail_id,))
        
        item = cursor.fetchone()
        if not item:
            logging.error(f"Item not found for invoice_detail_id: {invoice_detail_id}")
            return False

        # Розрахунок нової ціни з націнкою
        base_price = Decimal(item['invoice_price'])
        old_base_price = Decimal(item['old_base_price'])
        
        # Отримуємо націнку користувача
        cursor.execute("""
            SELECT r.markup_percentage
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = %s
        """, (item['user_id'],))
        
        markup_result = cursor.fetchone()
        if not markup_result:
            logging.error(f"No markup found for user_id: {item['user_id']}")
            return False
        
        markup_percentage = Decimal(markup_result[0])
        final_price = base_price * (1 + markup_percentage / 100)

        if action == 'update_price':
            # Оновлюємо ціни та відмітки про зміни
            cursor.execute("""
                UPDATE order_details 
                SET base_price = %s,
                    price = %s,
                    total_price = %s * quantity,
                    price_changed = true,
                    last_change_type = 'price_updated',
                    change_reason = %s
                WHERE id = %s
            """, (
                base_price, 
                final_price, 
                final_price, 
                f"Price updated from invoice (old: {old_base_price}, new: {base_price})",
                item['order_details_id']
            ))
            
            # Додаємо запис в історію змін
            cursor.execute("""
                INSERT INTO order_changes 
                (order_id, order_detail_id, field_changed, old_value, new_value, changed_by, change_date)
                VALUES (%s, %s, 'price', %s, %s, %s, NOW())
            """, (item['order_id'], item['order_details_id'], item['order_price'], final_price, 'invoice_process')) # Змінено тут

        logging.info(f"Price updated for order_detail_id: {item['order_details_id']}")
        return True

    except Exception as e:
        logging.error(f"Error handling price mismatch: {e}", exc_info=True)
        return False



def handle_no_tracking_code(invoice_detail_id, action, conn, cursor):
    """
    Обробляє ситуацію, коли в інвойсі відсутній код відстеження.
    """
    try:
        # Отримуємо інформацію про позицію інвойсу
        cursor.execute("""
            SELECT 
                id.article,
                id.quantity,
                id.price
            FROM invoice_details id
            WHERE id.id = %s
        """, (invoice_detail_id,))
        item = cursor.fetchone()

        if not item:
            logging.error(f"Item not found for invoice_detail_id: {invoice_detail_id}")
            return False

        if action == 'add_to_warehouse':
            # Додаємо товар на склад
            cursor.execute("""
                INSERT INTO warehouse (article, quantity, base_price, price, table_name, added_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (item['article'], item['quantity'], item['price'], item['price'], 'unknown'))
            logging.info(f"Added item {item['article']} to warehouse")

        # Оновлюємо статус деталі інвойсу
        cursor.execute("""
            UPDATE invoice_details 
            SET status = 'processed',
                processed_at = NOW()
            WHERE id = %s
        """, (invoice_detail_id,))
        logging.info(f"Updated invoice_detail status for id: {invoice_detail_id}")

        return True

    except Exception as e:
        logging.error(f"Error handling no tracking code: {e}", exc_info=True)
        return False


# Додаткові функції обробки невідповідностей в інвойсі
def handle_wrong_article(invoice_detail_id, correct_article, update_price, conn, cursor):
    """
    Обробляє невідповідність артикулів в інвойсі.
    """
    try:
        logging.info(f"handle_wrong_article called for invoice_detail_id: {invoice_detail_id}, correct_article: {correct_article}, update_price: {update_price}")
        # Отримуємо інформацію про позицію інвойсу
        cursor.execute("""
            SELECT 
                id.article,
                id.quantity as invoice_quantity,
                id.price as invoice_price,
                sod.order_details_id
            FROM invoice_details id
            JOIN supplier_order_details sod ON id.tracking_code = sod.tracking_code
            WHERE id.id = %s
        """, (invoice_detail_id,))
        
        item = cursor.fetchone()
        
        if not item:
            logging.error(f"Item not found for invoice_detail_id: {invoice_detail_id}")
            return False

        # Оновлюємо артикул в order_details
        cursor.execute("""
            UPDATE order_details 
            SET article = %s
            WHERE id = %s
        """, (correct_article, item['order_details_id']))
        logging.info(f"Updated order_details article for id: {item['order_details_id']} to {correct_article}")

        # Перевіряємо ціну
        invoice_price_per_unit = item['invoice_price'] / item['invoice_quantity']
        price_difference_percentage = abs((invoice_price_per_unit - item['invoice_price']) / item['invoice_price']) * 100

        if update_price and price_difference_percentage <= 1:
            # Оновлюємо ціну в order_details
            cursor.execute("""
                UPDATE order_details 
                SET price = %s,
                    total_price = %s * quantity
                WHERE id = %s
            """, (invoice_price_per_unit, invoice_price_per_unit, item['order_details_id']))
            logging.info(f"Updated order_details price for id: {item['order_details_id']} to {invoice_price_per_unit}")

        # Оновлюємо статус деталі інвойсу
        cursor.execute("""
            UPDATE invoice_details 
            SET status = 'processed',
                processed_at = NOW()
            WHERE id = %s
        """, (invoice_detail_id,))
        logging.info(f"Updated invoice_detail status for id: {invoice_detail_id}")

        return True

    except Exception as e:
        logging.error(f"Error handling wrong article: {e}", exc_info=True)
        return False





def get_markup_percentage(user_id):
    """Отримує відсоток націнки для користувача"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Отримуємо націнку з ролі користувача
        cursor.execute("""
            SELECT r.markup_percentage
            FROM users u
            JOIN user_roles ur ON u.id = ur.user_id
            JOIN roles r ON ur.role_id = r.id
            WHERE u.id = %s
        """, (user_id,))
        
        result = cursor.fetchone()
        markup = result[0] if result else 50.0  # За замовчуванням 50%
        
        return markup
        
    except Exception as e:
        logging.error(f"Error getting markup percentage: {e}", exc_info=True)
        return 50.0  # Повертаємо стандартну націнку у випадку помилки
        
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()



# Прийняти всі артикулі в замовленні користувача
@app.route('/<token>/admin/orders/<int:order_id>/accept-all', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def accept_all_items(token, order_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Перевіряємо чи є позиції зі статусом new
            cursor.execute("""
                SELECT COUNT(*) 
                FROM order_details 
                WHERE order_id = %s 
                AND status = 'new'
            """, (order_id,))
            
            unprocessed_count = cursor.fetchone()[0]
            
            if unprocessed_count == 0:
                flash("All items are already processed", "warning")
                return redirect(url_for('admin_order_details', token=token, order_id=order_id))

            # Оновлюємо тільки позиції зі статусом new
            cursor.execute("""
                UPDATE order_details 
                SET status = 'accepted',
                    processed_at = NOW()
                WHERE order_id = %s 
                AND status = 'new'
            """, (order_id,))
            
            # Оновлюємо статус замовлення
            cursor.execute("""
                UPDATE orders
                SET status = 'accepted'
                WHERE id = %s
                AND NOT EXISTS (
                    SELECT 1
                    FROM order_details
                    WHERE order_id = %s
                    AND status != 'accepted'
                )
            """, (order_id, order_id))
            
            conn.commit()
            flash("All items accepted successfully", "success")
            
    except Exception as e:
        logging.error(f"Error accepting all items: {e}")
        flash("Error processing items", "error")
        
    return redirect(url_for('admin_order_details', token=token, order_id=order_id))







@app.route('/<token>/admin/process-orders', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def process_orders(token):
    try:
        logging.info("Starting process_orders function")
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        sql_query = """
            SELECT 
                po.id as order_id,
                po.created_at,
                po.total_price,
                po.status,
                po.delivery_address,
                po.needs_invoice,
                po.invoice_details,
                u.username,
                u.id as user_id,
                u.email as user_email,
                COUNT(CASE WHEN pod.table_name = 'stock' THEN 1 END) as stock_items_count,
                COUNT(CASE WHEN pod.table_name != 'stock' THEN 1 END) as pricelist_items_count,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', pod.id,
                            'article', pod.article,
                            'table_name', pod.table_name,
                            'quantity', pod.quantity,
                            'price', pod.price,
                            'total_price', pod.total_price,
                            'comment', pod.comment,
                            'brand_id', pod.brand_id,
                            'status', pod.status,
                            'item_type', CASE 
                                WHEN pod.table_name = 'stock' THEN 'stock'
                                ELSE 'pricelist'
                            END
                        )
                    ) FILTER (WHERE pod.id IS NOT NULL),
                    '[]'::json
                ) as items
            FROM public_orders po
            JOIN users u ON po.user_id = u.id
            LEFT JOIN public_order_details pod ON po.id = pod.order_id
            GROUP BY po.id, po.created_at, po.total_price, po.status, 
                     po.delivery_address, po.needs_invoice, po.invoice_details, u.username, u.id, u.email
            ORDER BY po.created_at DESC
        """
        logging.info("Executing SQL query for orders")
        cursor.execute(sql_query)
        raw_orders = cursor.fetchall()
        logging.info(f"Found {len(raw_orders)} orders")
        
        # Перетворюємо у чисті Python об'єкти
        orders = []
        for raw_order in raw_orders:
            # Створюємо новий словник для кожного замовлення
            order = {
                'order_id': raw_order['order_id'],
                'created_at': raw_order['created_at'],
                'total_price': raw_order['total_price'],
                'status': raw_order['status'],
                'delivery_address': raw_order['delivery_address'],
                'needs_invoice': raw_order['needs_invoice'],
                'invoice_details': raw_order['invoice_details'],
                'username': raw_order['username'],
                'user_id': raw_order['user_id'],
                'user_email': raw_order['user_email'],
                'stock_items_count': raw_order['stock_items_count'],
                'pricelist_items_count': raw_order['pricelist_items_count'],
                'items_list': []  # Використовуємо нову назву, щоб уникнути конфлікту
            }
            
            # Обробляємо items - перевіряємо чи це був метод і конвертуємо в список
            items_value = raw_order['items']
            try:
                # Спробуємо перетворити на список, якщо це JSON-рядок
                if isinstance(items_value, str):
                    order['items_list'] = json.loads(items_value)
                # Якщо це вже об'єкт Python від PostgreSQL
                elif not callable(items_value) and items_value is not None:
                    order['items_list'] = items_value
            except Exception as e:
                logging.warning(f"Error processing items for order {order['order_id']}: {e}")
                order['items_list'] = []
            
            # Отримуємо попередні адреси та дані для рахунків-фактур
            if raw_order['user_id']:
                # Отримання збережених адрес доставки
                cursor.execute("""
                    SELECT id, country, city, postal_code, street, full_name, phone, is_default
                    FROM delivery_addresses
                    WHERE user_id = %s 
                    ORDER BY is_default DESC, created_at DESC
                """, (raw_order['user_id'],))
                order['saved_addresses'] = cursor.fetchall()
                
                # Виправлений запит для отримання збережених даних для рахунків-фактур
                cursor.execute("""
                    SELECT DISTINCT invoice_details, created_at
                    FROM public_orders
                    WHERE user_id = %s AND invoice_details IS NOT NULL AND invoice_details != '{}'
                    ORDER BY created_at DESC
                    LIMIT 5
                """, (raw_order['user_id'],))
                order['saved_invoices'] = [row['invoice_details'] for row in cursor.fetchall()]
            else:
                order['saved_addresses'] = []
                order['saved_invoices'] = []
                
            orders.append(order)
            logging.info(f"Processed order {order['order_id']} with {len(order['items_list'])} items")

        if request.method == 'POST':
            order_id = request.form.get('order_id')
            article = request.form.get('article')
            quantity = int(request.form.get('quantity', 0))
            item_type = request.form.get('item_type')
            action = request.form.get('action')
            order_detail_id = request.form.get('order_detail_id')

            logging.info(f"Processing order action - ID: {order_id}, Article: {article}, Action: {action}")

            # Додатково перевіряємо, чи оновлюємо адресу або дані для рахунку-фактури
            if action == 'update_address':
                address_id = request.form.get('delivery_address_id')
                if address_id:
                    # Отримуємо дані адреси
                    cursor.execute("""
                        SELECT * FROM delivery_addresses WHERE id = %s
                    """, (address_id,))
                    address = cursor.fetchone()
                    if address:
                        # Оновлюємо адресу в замовленні
                        cursor.execute("""
                            UPDATE public_orders
                            SET delivery_address = %s
                            WHERE id = %s
                        """, (json.dumps(dict(address)), order_id))
                        conn.commit()
                        flash(_("Delivery address updated"), "success")
                return redirect(url_for('process_orders', token=token))
                
            elif action == 'update_invoice':
                invoice_data = request.form.get('invoice_details')
                if invoice_data:
                    try:
                        invoice_json = json.loads(invoice_data)
                        # Оновлюємо дані для рахунку-фактури
                        cursor.execute("""
                            UPDATE public_orders
                            SET invoice_details = %s,
                                needs_invoice = true
                            WHERE id = %s
                        """, (json.dumps(invoice_json), order_id))
                        conn.commit()
                        flash(_("Invoice details updated"), "success")
                    except json.JSONDecodeError:
                        flash(_("Invalid invoice data format"), "error")
                return redirect(url_for('process_orders', token=token))

            elif item_type == 'stock':
                if action == 'accept_stock':
                    # Check stock availability first
                    cursor.execute("""
                        SELECT quantity FROM stock 
                        WHERE article = %s FOR UPDATE
                    """, (article,))
                    stock_item = cursor.fetchone()
                    
                    if not stock_item or stock_item['quantity'] < quantity:
                        flash(f"Insufficient stock for article {article}", "error")
                        return redirect(url_for('process_orders', token=token))

                    # Update order detail status
                    cursor.execute("""
                        UPDATE public_order_details
                        SET status = 'processing'
                        WHERE id = %s AND order_id = %s AND article = %s
                        RETURNING quantity
                    """, (order_detail_id, order_id, article))

                    # Update stock quantity
                    cursor.execute("""
                        UPDATE stock
                        SET quantity = quantity - %s
                        WHERE article = %s
                    """, (quantity, article))
                    
                    logging.info(f"Processed stock item - Article: {article}, Quantity: {quantity}")

                elif action == 'reject_stock':
                    cursor.execute("""
                        UPDATE public_order_details
                        SET status = 'rejected'
                        WHERE id = %s AND order_id = %s AND article = %s
                    """, (order_detail_id, order_id, article))
                    logging.info(f"Rejected stock item - Article: {article}")

            elif item_type == 'pricelist':
                if action == 'accept_pricelist':
                    cursor.execute("""
                        UPDATE public_order_details
                        SET status = 'ordered_supplier'
                        WHERE id = %s AND order_id = %s AND article = %s
                    """, (order_detail_id, order_id, article))
                    logging.info(f"Accepted pricelist item - Article: {article}")

                elif action == 'reject_pricelist':
                    cursor.execute("""
                        UPDATE public_order_details
                        SET status = 'rejected'
                        WHERE id = %s AND order_id = %s AND article = %s
                    """, (order_detail_id, order_id, article))
                    logging.info(f"Rejected pricelist item - Article: {article}")

            # Оновлюємо загальний статус замовлення на основі статусів деталей
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN status = 'processing' THEN 1 END) as processing,
                    COUNT(CASE WHEN status = 'ordered_supplier' THEN 1 END) as ordered,
                    COUNT(CASE WHEN status = 'rejected' THEN 1 END) as rejected,
                    COUNT(CASE WHEN status = 'new' OR status IS NULL THEN 1 END) as new
                FROM public_order_details 
                WHERE order_id = %s
            """, (order_id,))
            
            status_counts = cursor.fetchone()
            
            # Встановлюємо загальний статус замовлення
            new_status = 'new'
            if status_counts['total'] == status_counts['rejected']:
                new_status = 'rejected'
            elif status_counts['new'] == 0:
                if status_counts['processing'] > 0 and status_counts['ordered'] > 0:
                    new_status = 'processing'
                elif status_counts['processing'] > 0:
                    new_status = 'processing'
                elif status_counts['ordered'] > 0:
                    new_status = 'ordered_supplier'
            
            cursor.execute("""
                UPDATE public_orders 
                SET status = %s
                WHERE id = %s
            """, (new_status, order_id))
            logging.info(f"Updated order status to {new_status}")

            conn.commit()
            flash(_("Item processed successfully"), "success")
            return redirect(url_for('process_orders', token=token))

        return render_template(
            'admin/orders/process_orders.html',
            orders=orders,
            token=token
        )

    except Exception as e:
        logging.error(f"Error in process_orders: {e}", exc_info=True)
        if 'conn' in locals():
            conn.rollback()
        flash(_("Error processing orders"), "error")
        return redirect(url_for('admin_dashboard', token=token))

    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()
        logging.info("Database connection closed")



# додавання фото
@app.route('/<token>/admin/add_product_images', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def add_product_images(token):
    if request.method == 'POST':
        conn = None
        try:
            data = request.form.get('images_data')
            logging.info("Starting image import process")
            
            if not data:
                logging.warning("No image data provided")
                flash("Please enter image data", "warning")
                return redirect(url_for('add_product_images', token=token))

            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_images (
                    id SERIAL PRIMARY KEY,
                    product_article TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT unique_article_url UNIQUE (product_article, image_url)
                )
            """)
            conn.commit()  # Commit table creation
            
            added = 0
            errors = 0
            skipped = 0
            
            for line in data.splitlines():
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    logging.info(f"Processing line: {line}")
                    parts = line.split('\t')
                    
                    if len(parts) != 2:
                        logging.error(f"Invalid line format (expected 2 parts, got {len(parts)}): {line}")
                        errors += 1
                        continue
                        
                    article, image_url = parts
                    article = article.strip()
                    image_url = image_url.strip()
                    
                    logging.info(f"Attempting to insert: Article={article}, URL={image_url}")
                    
                    try:
                        cursor.execute("""
                            INSERT INTO product_images (product_article, image_url)
                            VALUES (%s, %s)
                            ON CONFLICT ON CONSTRAINT unique_article_url DO NOTHING
                        """, (article, image_url))
                        conn.commit()  # Commit each insert
                        
                        if cursor.rowcount > 0:
                            added += 1
                            logging.info(f"Successfully added image for article {article}")
                        else:
                            skipped += 1
                            logging.info(f"Skipped duplicate image for article {article}")
                            
                    except psycopg2.Error as e:
                        logging.warning(f"Database error for {article}: {e}")
                        conn.rollback()  # Rollback on error
                        errors += 1
                        continue
                        
                except Exception as e:
                    logging.error(f"Error processing line '{line}': {str(e)}")
                    errors += 1
                    continue
            
            message_parts = []
            if added > 0:
                message_parts.append(f"Added {added} images")
            if skipped > 0:
                message_parts.append(f"Skipped {skipped} duplicates")
            if errors > 0:
                message_parts.append(f"Failed to process {errors} lines")
                
            flash(", ".join(message_parts), "success" if added > 0 else "warning")
            logging.info(f"Import completed: {added} added, {skipped} skipped, {errors} errors")
                
        except Exception as e:
            logging.error(f"Critical error during image import: {str(e)}", exc_info=True)
            flash(f"Error occurred while adding images: {str(e)}", "danger")
            if conn:
                conn.rollback()
            
        finally:
            if conn:
                conn.close()
                logging.info("Database connection closed")
                
        return redirect(url_for('add_product_images', token=token))

    return render_template('admin/products/add_images.html', token=token)


@app.route('/<token>/admin/manage-descriptions', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def manage_descriptions(token):
    """
    Відображає сторінку керування описами товарів
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Отримуємо список товарів з описами
        cursor.execute("""
            SELECT 
                article,
                brand_id,
                name_uk, description_uk,
                name_en, description_en,
                name_sk, description_sk,
                name_pl, description_pl
            FROM products
            ORDER BY article
        """)
        
        products = cursor.fetchall()
        
        return render_template(
            'admin/products/manage_descriptions.html',
            products=products,
            token=token
        )
        
    except Exception as e:
        logging.error(f"Error managing descriptions: {e}")
        flash("Error loading product descriptions", "error")
        return redirect(url_for('admin_dashboard', token=token))
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/<token>/admin/update-description', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def update_description(token):
    try:
        article = request.form.get('article')
        brand_id = request.form.get('brand_id')
        
        if not all([article, brand_id]):
            return jsonify({'error': 'Missing required fields'}), 400
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update descriptions for all languages
        cursor.execute("""
            UPDATE products 
            SET name_uk = %s, description_uk = %s,
                name_en = %s, description_en = %s,
                name_sk = %s, description_sk = %s,
                name_pl = %s, description_pl = %s
            WHERE article = %s AND brand_id = %s
        """, (
            request.form.get('name_uk'), request.form.get('description_uk'),
            request.form.get('name_en'), request.form.get('description_en'),
            request.form.get('name_sk'), request.form.get('description_sk'),
            request.form.get('name_pl'), request.form.get('description_pl'),
            article, brand_id
        ))
        
        conn.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        logging.error(f"Error updating description: {e}")
        return jsonify({'error': str(e)}), 500
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/<token>/admin/add_product_descriptions', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def add_product_descriptions(token):
    if request.method == 'POST':
        try:
            data = request.form.get('descriptions_data')
            language = request.form.get('language')
            update_mode = request.form.get('update_mode', 'create') # create або update
            
            if not all([data, language]):
                flash("Будь ласка, заповніть всі поля", "warning") 
                return redirect(url_for('add_product_descriptions', token=token))

            conn = get_db_connection()
            cursor = conn.cursor()
            
            added = 0
            updated = 0
            errors = 0
            
            for line in data.splitlines():
                if not line.strip():
                    continue
                    
                parts = line.split('\t')
                if len(parts) < 4:
                    errors += 1
                    continue
                    
                article, brand_id, name, description = parts[:4]
                
                try:
                    # Перевіряємо чи існує товар
                    cursor.execute(f"""
                        SELECT id FROM products 
                        WHERE article = %s
                    """, (article,))
                    
                    exists = cursor.fetchone()
                    
                    if exists:
                        if update_mode == 'update':
                            # Оновлюємо існуючий опис
                            cursor.execute(f"""
                                UPDATE products 
                                SET name_{language} = %s,
                                    description_{language} = %s
                                WHERE article = %s
                            """, (name, description, article))
                            updated += 1
                    else:
                        # Створюємо новий запис
                        cursor.execute(f"""
                            INSERT INTO products (
                                article, brand_id, name_{language}, description_{language}
                            ) VALUES (%s, %s, %s, %s)
                        """, (article, brand_id, name, description))
                        added += 1
                        
                    conn.commit()
                    
                except Exception as e:
                    errors += 1
                    logging.error(f"Error processing line: {line}. Error: {str(e)}")
                    continue
                    
            flash(f"Додано: {added}, Оновлено: {updated}, Помилок: {errors}", "success")
            
        except Exception as e:
            flash(f"Помилка: {str(e)}", "error")
            
        finally:
            if conn:
                conn.close()
                
        return redirect(url_for('add_product_descriptions', token=token))
        
    return render_template('admin/products/add_descriptions.html', token=token)




@app.route('/user-profile', methods=['GET', 'POST'])
def public_user_profile():
    """
    Кабінет для публічного користувача
    """
    user_id = session.get('user_id')
    if not user_id:
        flash(_("Please login to access your profile"), "error")
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Отримуємо дані користувача
        cursor.execute("""
            SELECT id, username, email, phone, preferred_language
            FROM users
            WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()

        # Отримуємо збережені адреси доставки
        cursor.execute("""
            SELECT id, country, city, postal_code, street, full_name, 
                   phone, is_default, created_at
            FROM delivery_addresses
            WHERE user_id = %s
            ORDER BY is_default DESC, created_at DESC
        """, (user_id,))
        addresses = cursor.fetchall()
        
        # Отримуємо дані компаній користувача
        cursor.execute("""
            SELECT id, company_name, vat_number, registration_number, 
                   address, is_default, created_at
            FROM user_companies
            WHERE user_id = %s
            ORDER BY is_default DESC, created_at DESC
        """, (user_id,))
        companies = cursor.fetchall()

        # POST запит для оновлення профілю
        if request.method == 'POST':
            action = request.form.get('action', '')
            
            # Оновлення основної інформації
            if action == 'update_profile':
                email = request.form.get('email')
                phone = request.form.get('phone')
                preferred_language = request.form.get('preferred_language')
                current_password = request.form.get('current_password')
                new_password = request.form.get('new_password')
                confirm_password = request.form.get('confirm_password')
                
                # Валідація email
                if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                    flash(_("Invalid email format"), "error")
                    return redirect(url_for('public_user_profile'))
                
                # Перевірка чи вже використовується email або телефон іншим користувачем
                if email != user['email']:
                    cursor.execute("SELECT id FROM users WHERE email = %s AND id != %s", (email, user_id))
                    if cursor.fetchone():
                        flash(_("This email is already in use by another user"), "error")
                        return redirect(url_for('public_user_profile'))
                
                if phone and phone != user['phone']:
                    cursor.execute("SELECT id FROM users WHERE phone = %s AND id != %s", (phone, user_id))
                    if cursor.fetchone():
                        flash(_("This phone number is already in use by another user"), "error")
                        return redirect(url_for('public_user_profile'))
                
                try:
                    # Оновлення паролю, якщо вказано поточний і новий пароль
                    if current_password and new_password:
                        # Перевірка поточного паролю
                        cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
                        stored_hash = cursor.fetchone()[0]
                        
                        if not verify_password(current_password, stored_hash):
                            flash(_("Current password is incorrect"), "error")
                            return redirect(url_for('public_user_profile'))
                        
                        # Перевірка, що нові паролі співпадають
                        if new_password != confirm_password:
                            flash(_("New passwords do not match"), "error")
                            return redirect(url_for('public_user_profile'))
                        
                        # Хешування нового паролю
                        password_hash = hash_password(new_password)
                        
                        # Оновлення даних користувача з новим паролем
                        cursor.execute("""
                            UPDATE users 
                            SET email = %s, phone = %s, preferred_language = %s, password_hash = %s
                            WHERE id = %s
                        """, (email, phone, preferred_language, password_hash, user_id))
                        
                        flash(_("Profile and password updated successfully"), "success")
                    else:
                        # Оновлення тільки email і телефону
                        cursor.execute("""
                            UPDATE users 
                            SET email = %s, phone = %s, preferred_language = %s
                            WHERE id = %s
                        """, (email, phone, preferred_language, user_id))
                        
                        # Оновлюємо мову в сесії
                        session['language'] = preferred_language
                        session.modified = True
                        
                        flash(_("Profile updated successfully"), "success")
                    
                    conn.commit()
                except psycopg2.errors.UniqueViolation as e:
                    conn.rollback()
                    if "idx_users_email" in str(e):
                        flash(_("This email is already in use by another user"), "error")
                    elif "idx_users_phone" in str(e):
                        flash(_("This phone number is already in use by another user"), "error")
                    else:
                        flash(_("Error updating profile: duplicate value"), "error")
                    return redirect(url_for('public_user_profile'))
                
                return redirect(url_for('public_user_profile'))
                
            # Додавання нової адреси
            elif action == 'add_address':
                country = request.form.get('country')
                city = request.form.get('city')
                postal_code = request.form.get('postal_code')
                street = request.form.get('street')
                full_name = request.form.get('full_name')
                phone = request.form.get('address_phone')
                is_default = 'is_default' in request.form
                
                if is_default:
                    # Скидаємо попередню адресу за замовчуванням
                    cursor.execute("""
                        UPDATE delivery_addresses 
                        SET is_default = false
                        WHERE user_id = %s
                    """, (user_id,))
                
                # Додаємо нову адресу
                cursor.execute("""
                    INSERT INTO delivery_addresses 
                    (user_id, country, city, postal_code, street, full_name, phone, is_default)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, country, city, postal_code, street, full_name, phone, is_default))
                
                conn.commit()
                flash(_("Address added successfully"), "success")
                return redirect(url_for('public_user_profile'))
                
            # Видалення адреси
            elif action == 'delete_address' and request.form.get('address_id'):
                address_id = request.form.get('address_id')
                cursor.execute("""
                    DELETE FROM delivery_addresses 
                    WHERE id = %s AND user_id = %s
                """, (address_id, user_id))
                
                conn.commit()
                flash(_("Address deleted successfully"), "success")
                return redirect(url_for('public_user_profile'))
                
            # Встановлення адреси за замовчуванням
            elif action == 'set_default_address' and request.form.get('address_id'):
                address_id = request.form.get('address_id')
                
                # Скидаємо всі адреси
                cursor.execute("""
                    UPDATE delivery_addresses 
                    SET is_default = false
                    WHERE user_id = %s
                """, (user_id,))
                
                # Встановлюємо нову адресу за замовчуванням
                cursor.execute("""
                    UPDATE delivery_addresses 
                    SET is_default = true
                    WHERE id = %s AND user_id = %s
                """, (address_id, user_id))
                
                conn.commit()
                flash(_("Default address updated"), "success")
                return redirect(url_for('public_user_profile'))
                
            # Додавання нової компанії
            elif action == 'add_company':
                company_name = request.form.get('company_name')
                vat_number = request.form.get('vat_number')
                registration_number = request.form.get('registration_number')
                address = request.form.get('company_address')
                is_default = 'is_default' in request.form
                
                if is_default:
                    # Скидаємо попередню компанію за замовчуванням
                    cursor.execute("""
                        UPDATE user_companies 
                        SET is_default = false
                        WHERE user_id = %s
                    """, (user_id,))
                
                # Додаємо нову компанію
                cursor.execute("""
                    INSERT INTO user_companies 
                    (user_id, company_name, vat_number, registration_number, address, is_default)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, company_name, vat_number, registration_number, address, is_default))
                
                conn.commit()
                flash(_("Company added successfully"), "success")
                return redirect(url_for('public_user_profile'))
                
            # Видалення компанії
            elif action == 'delete_company' and request.form.get('company_id'):
                company_id = request.form.get('company_id')
                cursor.execute("""
                    DELETE FROM user_companies 
                    WHERE id = %s AND user_id = %s
                """, (company_id, user_id))
                
                conn.commit()
                flash(_("Company deleted successfully"), "success")
                return redirect(url_for('public_user_profile'))
                
            # Встановлення компанії за замовчуванням
            elif action == 'set_default_company' and request.form.get('company_id'):
                company_id = request.form.get('company_id')
                
                # Скидаємо всі компанії
                cursor.execute("""
                    UPDATE user_companies 
                    SET is_default = false
                    WHERE user_id = %s
                """, (user_id,))
                
                # Встановлюємо нову компанію за замовчуванням
                cursor.execute("""
                    UPDATE user_companies 
                    SET is_default = true
                    WHERE id = %s AND user_id = %s
                """, (company_id, user_id))
                
                conn.commit()
                flash(_("Default company updated"), "success")
                return redirect(url_for('public_user_profile'))

        return render_template(
            'public/user/profile.html',
            user=user,
            addresses=addresses,
            companies=companies,
            available_languages=[('uk', _('Ukrainian')), ('en', _('English')), ('sk', _('Slovak')), ('pl', _('Polish'))]
        )

    except Exception as e:
        conn.rollback()
        logging.error(f"Error in user_profile: {e}", exc_info=True)
        flash(_("Error accessing user profile"), "error")
        return redirect(url_for('index'))

    finally:
        cursor.close()
        conn.close()


@app.route('/terms')
def terms():
    return render_template('public/terms.html')


@app.route('/privacy')
def privacy():
    return render_template('public/privacy.html')




# маршрут для відправки інвойсів publik users
@app.route('/<token>/admin/orders/<int:order_id>/send_invoice', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_send_invoice(token, order_id):
    """Дозволяє адміністратору завантажити інвойс та відправити його клієнту"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Отримуємо інформацію про замовлення
        cursor.execute("""
            SELECT o.*, u.email, u.username, u.preferred_language
            FROM public_orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.id = %s
        """, (order_id,))
        order = cursor.fetchone()
        
        if not order:
            flash("Order not found", "error")
            return redirect(url_for('process_orders', token=token))
        
        # Отримуємо деталі замовлення
        cursor.execute("""
            SELECT d.*, b.name as brand_name
            FROM public_order_details d
            LEFT JOIN brands b ON d.brand_id = b.id
            WHERE d.order_id = %s
        """, (order_id,))
        order_items = cursor.fetchall()
        
        # Якщо POST-запит - обробляємо відправку інвойсу
        if request.method == 'POST':
            # Отримуємо дані форми
            delivery_cost = Decimal(request.form.get('delivery_cost', '0'))
            delivery_info = request.form.get('delivery_info', '')
            is_self_pickup = request.form.get('is_self_pickup') == 'on'
            
            # Якщо самовивіз, встановлюємо вартість доставки в 0
            if is_self_pickup:
                delivery_cost = Decimal('0')
                if not delivery_info:
                    delivery_info = "Self pickup"
                    
            # Отримуємо завантажений файл
            invoice_file = request.files.get('invoice_file')
            if not invoice_file:
                flash("Invoice file is required", "error")
                return redirect(request.url)
                
            # Перевіряємо тип файлу (дозволяємо PDF)
            if not invoice_file.filename.lower().endswith(('.pdf')):
                flash("Only PDF files are allowed", "error")
                return redirect(request.url)
                
            # Зберігаємо файл
            filename = secure_filename(f"invoice_order_{order_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
            file_path = os.path.join(app.config.get('UPLOAD_FOLDER', 'uploads'), filename)
            
            # Створюємо директорію, якщо вона не існує
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            invoice_file.save(file_path)
            
            # Обчислюємо загальну вартість з урахуванням доставки
            order_total = Decimal(str(order['total_price']))
            total_with_delivery = order_total + delivery_cost
            
            # Оновлюємо замовлення в базі даних
            cursor.execute("""
                UPDATE public_orders
                SET 
                    delivery_cost = %s,
                    delivery_info = %s,
                    is_self_pickup = %s,
                    invoice_path = %s,
                    invoice_sent_at = NOW(),
                    status = 'invoice_sent',
                    payment_status = 'awaiting_payment',
                    updated_at = NOW()
                WHERE id = %s
            """, (
                delivery_cost,
                delivery_info,
                is_self_pickup,
                filename,
                order_id
            ))
            
            conn.commit()
            
            # Отримуємо мову користувача
            user_lang = order['preferred_language'] or 'sk'
            if user_lang == 'uk':  # Якщо мова українська, використовуємо словацьку
                user_lang = 'sk'
                
            # Відправляємо email з інвойсом
            email_items = []
            for item in order_items:
                email_items.append({
                    'article': item['article'],
                    'price': float(item['price']),
                    'quantity': item['quantity'],
                    'delivery_time': "Processed"
                })
                
            # Створюємо копію даних доставки
            delivery_data = json.loads(order['delivery_address']) if order['delivery_address'] else {}
            
            # Додаємо інформацію про доставку
            delivery_data['delivery_cost'] = float(delivery_cost)
            delivery_data['delivery_info'] = delivery_info
            delivery_data['is_self_pickup'] = is_self_pickup
            delivery_data['total_with_delivery'] = float(total_with_delivery)
                
            # Відправляємо email
            success = send_invoice_email(
                to_email=order['email'],
                subject=f"Invoice for Order #{order_id}",
                ordered_items=email_items,
                delivery_data=delivery_data,
                invoice_path=file_path,
                lang=user_lang
            )
            
            if success:
                flash("Invoice sent successfully!", "success")
            else:
                flash("Error sending invoice email", "error")
                
            return redirect(url_for('process_orders', token=token))
        
        # GET-запит - відображаємо форму
        return render_template(
            'admin/orders/send_invoice.html',
            order=order,
            order_items=order_items,
            token=token,
            order_id=order_id
        )
        
    except Exception as e:
        logging.error(f"Error sending invoice: {e}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('process_orders', token=token))
            
    finally:
        if 'conn' in locals() and conn:
            conn.close()

#відправка email з вкладенням
def send_invoice_email(to_email, subject, ordered_items, delivery_data, invoice_path, lang='en'):
    """
    Відправляє email з деталями замовлення та прикріпленим інвойсом
    """
    try:
        logging.info(f"Відправка інвойсу на {to_email} мовою {lang}")
        
        # Налаштування SMTP
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT"))
        sender_email = os.getenv("SMTP_EMAIL")
        sender_password = os.getenv("SMTP_PASSWORD")
        
        # Використовуємо sender_email як bcc_email
        bcc_email = sender_email
        
        if not sender_email or not sender_password:
            logging.error("Не вказані SMTP облікові дані в змінних середовища")
            return False

        # Словник перекладів для кожної мови
        translations = {
            'sk': {
                'subject': 'Faktúra k objednávke',
                'greeting': 'Vážený zákazník,',
                'order_details': 'Detaily objednávky:',
                'delivery_info': 'Dodacie údaje:',
                'delivery_cost': 'Náklady na dopravu:',
                'self_pickup': 'Osobný odber',
                'total_with_delivery': 'Celková cena s dopravou:',
                'payment_instruction': 'Prosím, uhraďte faktúru podľa pokynov v priloženom dokumente.',
                'invoice_attached': 'Faktúra je priložená k tomuto e-mailu.',
                'thank_you': 'Ďakujeme za Váš nákup!',
                'contact_us': 'V prípade otázok nás kontaktujte',
                'footer_text': 'Tento e-mail bol vygenerovaný automaticky. Prosím, neodpovedajte naň.'
            },
            'en': {
                'subject': 'Invoice for your order',
                'greeting': 'Dear customer,',
                'order_details': 'Order details:',
                'delivery_info': 'Delivery information:',
                'delivery_cost': 'Delivery cost:',
                'self_pickup': 'Self pickup',
                'total_with_delivery': 'Total price with delivery:',
                'payment_instruction': 'Please pay the invoice according to the instructions in the attached document.',
                'invoice_attached': 'The invoice is attached to this email.',
                'thank_you': 'Thank you for your purchase!',
                'contact_us': 'If you have any questions, please contact us',
                'footer_text': 'This email was generated automatically. Please do not reply to it.'
            },
            'pl': {
                'subject': 'Faktura za zamówienie',
                'greeting': 'Szanowny Kliencie,',
                'order_details': 'Szczegóły zamówienia:',
                'delivery_info': 'Informacje o dostawie:',
                'delivery_cost': 'Koszt dostawy:',
                'self_pickup': 'Odbiór osobisty',
                'total_with_delivery': 'Łączna cena z dostawą:',
                'payment_instruction': 'Prosimy o opłacenie faktury zgodnie z instrukcjami w załączonym dokumencie.',
                'invoice_attached': 'Faktura jest dołączona do tego e-maila.',
                'thank_you': 'Dziękujemy za zakupy!',
                'contact_us': 'W razie pytań prosimy o kontakt',
                'footer_text': 'Ten e-mail został wygenerowany automatycznie. Prosimy na niego nie odpowiadać.'
            }
        }

        # Використовуємо переклад для вибраної мови або англійську як запасну
        t = translations.get(lang, translations['en'])
        
        # Рахуємо загальну суму для шаблону
        total_sum = 0
        for item in ordered_items:
            price = float(item['price'])
            quantity = int(item['quantity'])
            total_sum += price * quantity
        
        # Відображаємо текстову версію
        text_content = render_template(
            'emails/invoice_email.txt',
            t=t,
            delivery_data=delivery_data,
            ordered_items=ordered_items,
            total_sum=total_sum,
            subject=subject or t['subject']
        )

        # Відображаємо HTML версію
        html_content = render_template(
            'emails/invoice_email.html',
            t=t,
            delivery_data=delivery_data,
            ordered_items=ordered_items,
            total_sum=total_sum,
            subject=subject or t['subject'],
            current_year=datetime.now().year
        )

        # Формуємо повідомлення з текстовою та HTML версіями
        message = MIMEMultipart('alternative')
        message["From"] = sender_email
        message["To"] = to_email
        message["Subject"] = subject if subject else t['subject']
        
        # Додаємо обидві версії
        message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))
        
        # Прикріплюємо файл інвойсу
        with open(invoice_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            
        # Кодуємо в base64
        encoders.encode_base64(part)
        
        # Додаємо заголовки
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={os.path.basename(invoice_path)}",
        )
        
        # Додаємо вкладення до повідомлення
        message.attach(part)

        # Відправка email
        try:
            # Використовуємо SSL для порту 465
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            
            # Вимикаємо детальне логування
            server.set_debuglevel(0)
            
            # Аутентифікація
            server.login(sender_email, sender_password)
            
            # Відправка (включаємо основного отримувача і BCC)
            recipients = [to_email]
            # Додаємо BCC тільки якщо він відрізняється від основного отримувача
            if bcc_email and bcc_email != to_email:
                recipients.append(bcc_email)
                
            server.sendmail(sender_email, recipients, message.as_string())
            logging.info(f"Інвойс успішно надіслано до {to_email}" + 
                         (f" та копію ({bcc_email})" if bcc_email != to_email else ""))
            server.quit()
            return True
            
        except smtplib.SMTPConnectError as e:
            logging.error(f"Помилка з'єднання SMTP: {e}")
            return False
        except smtplib.SMTPAuthenticationError as e:
            logging.error(f"Помилка аутентифікації SMTP: {e}")
            return False
        except smtplib.SMTPException as e:
            logging.error(f"Помилка SMTP: {e}")
            return False
        except ConnectionError as e:
            logging.error(f"Помилка з'єднання: {e}")
            return False
        
    except Exception as e:
        logging.error(f"Не вдалося надіслати інвойс до {to_email}: {str(e)}")
        return False



@app.route('/<token>/admin/sitemaps', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_sitemaps(token):
    """Сторінка управління sitemap файлами"""
    try:
        # Отримуємо список всіх файлів sitemap
        sitemap_files = []
        if os.path.exists(SITEMAP_DIR):
            files = os.listdir(SITEMAP_DIR)
            for file in files:
                file_path = os.path.join(SITEMAP_DIR, file)
                file_size = os.path.getsize(file_path) / 1024  # KB
                modified_date = datetime.fromtimestamp(os.path.getmtime(file_path))
                sitemap_files.append({
                    'name': file,
                    'size': f"{file_size:.2f} KB",
                    'modified': modified_date
                })
        
        # Сортуємо файли за іменем
        sitemap_files.sort(key=lambda x: x['name'])
        
        # Отримуємо налаштування планувальника
        scheduler_jobs = []
        for job in scheduler.get_jobs():
            if job.id.startswith('generate_sitemap'):
                scheduler_jobs.append({
                    'id': job.id,
                    'next_run': job.next_run_time,
                    'trigger': str(job.trigger)
                })
        
        return render_template(
            'admin/sitemaps/manage_sitemaps.html',
            token=token,
            sitemap_files=sitemap_files,
            scheduler_jobs=scheduler_jobs,
            sitemap_dir=SITEMAP_DIR,
            show_scheduler_details_link=True  # Додано для відображення посилання
        )
    except Exception as e:
        logging.error(f"Error in admin_sitemaps: {e}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('admin_dashboard', token=token))

@app.route('/<token>/admin/sitemaps/generate', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_generate_sitemaps(token):
    generation_type = request.form.get('type', 'all')
    
    try:
        if generation_type == 'all':
            success = generate_all_sitemaps()  # БЕЗ other файлів
            message = "All sitemaps generated successfully (excluding Other products)"
        elif generation_type == 'static':
            success = generate_sitemap_static_file()
            message = "Static sitemap generated successfully"
        elif generation_type == 'categories':
            success = generate_sitemap_categories_file()
            message = "Categories sitemap generated successfully"
        elif generation_type == 'stock':
            success = generate_sitemap_stock_files()
            message = "Stock sitemaps generated successfully"
        elif generation_type == 'enriched':
            success = generate_sitemap_enriched_files()
            message = "Enriched sitemaps generated successfully"
        elif generation_type == 'other':
            success = generate_sitemap_other_files()  # ОКРЕМО для Other
            message = "Other products sitemaps generated successfully"
        elif generation_type == 'images':
            success = generate_sitemap_images_file()
            message = "Images sitemap generated successfully"
        elif generation_type == 'index':
            success = generate_sitemap_index_file()
            message = "Sitemap index generated successfully"
        else:
            flash("Invalid generation type", "error")
            return redirect(url_for('admin_sitemaps', token=token))
        
        if success:
            flash(message, "success")
        else:
            flash("Error generating sitemaps", "error")
            
    except Exception as e:
        logging.error(f"Error in admin_generate_sitemaps: {e}", exc_info=True)
        flash(f"Error generating sitemaps: {str(e)}", "error")
    
    return redirect(url_for('admin_sitemaps', token=token))

@app.route('/<token>/admin/sitemaps/view/<filename>')
@requires_token_and_roles('admin')
@add_noindex_header
def admin_view_sitemap(token, filename):
    """Перегляд вмісту sitemap файлу"""
    try:
        file_path = os.path.join(SITEMAP_DIR, filename)
        if not os.path.exists(file_path):
            flash(f"File {filename} not found", "error")
            return redirect(url_for('admin_sitemaps', token=token))
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Додаємо підсвічування синтаксису для XML файлів
        return render_template(
            'admin/sitemaps/view_sitemap.html',
            token=token,
            filename=filename,
            content=content,
            file_path=file_path
        )
    except Exception as e:
        logging.error(f"Error in admin_view_sitemap: {e}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('admin_sitemaps', token=token))

@app.route('/<token>/admin/sitemaps/delete/<filename>', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_delete_sitemap(token, filename):
    """Видалення sitemap файлу"""
    try:
        file_path = os.path.join(SITEMAP_DIR, filename)
        if not os.path.exists(file_path):
            flash(f"File {filename} not found", "error")
            return redirect(url_for('admin_sitemaps', token=token))
        
        os.remove(file_path)
        flash(f"File {filename} deleted successfully", "success")
        return redirect(url_for('admin_sitemaps', token=token))
    except Exception as e:
        logging.error(f"Error in admin_delete_sitemap: {e}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('admin_sitemaps', token=token))


@app.route('/generate-sitemaps/<secret_key>')
def manual_generate_sitemaps(secret_key):
    """Ручний запуск генерації sitemaps через URL (захищений секретним ключем)"""
    # Секретний ключ для захисту від несанкціонованого доступу
    if secret_key != os.getenv('SITEMAP_SECRET_KEY', 'your_default_secret_key'):
        return "Unauthorized", 401
        
    logging.info("Starting manual sitemap generation process")
    
    # Перевіряємо доступ до каталогу
    try:
        os.makedirs(SITEMAP_DIR, exist_ok=True)
        logging.info(f"SITEMAP_DIR: {SITEMAP_DIR}")
        logging.info(f"Directory exists: {os.path.exists(SITEMAP_DIR)}")
        logging.info(f"Directory is writable: {os.access(SITEMAP_DIR, os.W_OK)}")
    except Exception as e:
        logging.error(f"Directory error: {e}")
    
    try:
        # Генеруємо всі файли
        generate_all_sitemaps()
        return "Sitemap generation completed successfully!", 200
    except Exception as e:
        logging.error(f"Error during manual sitemap generation: {e}", exc_info=True)
        return f"Error: {str(e)}", 500

@app.route('/sitemap.xml', endpoint='sitemap_xml')
def sitemap():
    """Redirect to sitemap index"""
    logging.info("sitemap() function redirecting to sitemap-index.xml")  
    return redirect(url_for('sitemap_index_xml'))

@app.route('/sitemap-images.xml', endpoint='sitemap_images_xml')
def sitemap_images_route():
    """Serve pre-generated sitemap images XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, 'sitemap-images.xml')
    
    # Якщо файл не існує, генеруємо його
    if not os.path.exists(sitemap_path):
        logging.info(f"sitemap-images.xml not found at {sitemap_path}, generating...")
        
        try:
            # Генеруємо файл
            generate_sitemap_images_file()
            
            # Додаткова перевірка
            if not os.path.exists(sitemap_path):
                logging.error(f"Failed to generate sitemap-images.xml at {sitemap_path}")
                return "Error generating sitemap", 500
                
        except Exception as e:
            logging.error(f"Error generating sitemap images: {e}", exc_info=True)
            return "Error generating sitemap", 500
    
    try:
        # Подаємо файл з каталогу static/sitemaps
        return send_from_directory(os.path.dirname(sitemap_path), 
                                  os.path.basename(sitemap_path), 
                                  mimetype='application/xml')
    except Exception as e:
        logging.error(f"Error serving sitemap file: {e}", exc_info=True)
        return "Error serving sitemap", 500


@app.route('/sitemap-index.xml', endpoint='sitemap_index_xml')
def sitemap_index():
    """Serve pre-generated sitemap index XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, 'sitemap-index.xml')
    
    # Якщо файл не існує, генеруємо його
    if not os.path.exists(sitemap_path):
        logging.info(f"sitemap-index.xml not found at {sitemap_path}, generating...")
        
        try:
            # Генеруємо файл індексу
            generate_sitemap_index_file()
            
            # Додаткова перевірка
            if not os.path.exists(sitemap_path):
                logging.error(f"Failed to generate sitemap-index.xml at {sitemap_path}")
                return "Error generating sitemap", 500
                
        except Exception as e:
            logging.error(f"Error generating sitemap index: {e}", exc_info=True)
            return "Error generating sitemap", 500
    
    try:
        # Пробуємо подати файл зі static/sitemaps
        return send_from_directory(os.path.dirname(sitemap_path), os.path.basename(sitemap_path), mimetype='application/xml')
    except Exception as e:
        logging.error(f"Error serving sitemap file: {e}", exc_info=True)
        return "Error serving sitemap", 500

@app.route('/sitemap-static.xml')
def sitemap_static():
    """Serve pre-generated static sitemap XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, 'sitemap-static.xml')
    
    # Якщо файл не існує, генеруємо його
    if not os.path.exists(sitemap_path):
        generate_sitemap_static_file()
    
    return send_from_directory(os.path.dirname(sitemap_path), os.path.basename(sitemap_path), mimetype='application/xml')

@app.route('/sitemap-categories.xml', endpoint='sitemap_categories_xml')
def sitemap_categories():
    """Serve pre-generated categories sitemap XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, 'sitemap-categories.xml')
    
    # Якщо файл не існує, генеруємо його
    if not os.path.exists(sitemap_path):
        generate_sitemap_categories_file()
    
    return send_from_directory(os.path.dirname(sitemap_path), os.path.basename(sitemap_path), mimetype='application/xml')


@app.route('/sitemap-stock-<int:page>.xml', endpoint='sitemap_stock_xml')
def sitemap_stock(page):
    """Serve pre-generated stock sitemap XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, f'sitemap-stock-{page}.xml')
    
    # Детальне логування для відлагодження
    logging.info(f"Request for sitemap-stock-{page}.xml, checking path: {sitemap_path}")
    
    # Перевіряємо, чи існує файл
    if not os.path.exists(sitemap_path):
        logging.warning(f"sitemap-stock-{page}.xml not found, redirecting to index")
        
        # Додайте цей код для перевірки дозволів і структури каталогу
        try:
            logging.info(f"SITEMAP_DIR exists: {os.path.exists(SITEMAP_DIR)}")
            logging.info(f"SITEMAP_DIR contents: {os.listdir(SITEMAP_DIR) if os.path.exists(SITEMAP_DIR) else 'directory not found'}")
        except Exception as e:
            logging.error(f"Error checking SITEMAP_DIR: {e}")
            
        return redirect(url_for('sitemap_index_xml'))
    
    # Файл існує, повертаємо його
    logging.info(f"sitemap-stock-{page}.xml found, serving file")
    return send_from_directory(os.path.dirname(sitemap_path), os.path.basename(sitemap_path), mimetype='application/xml')



@app.route('/sitemap-enriched-<int:page>.xml', endpoint='sitemap_enriched_xml')
def sitemap_enriched(page):
    """Serve pre-generated enriched sitemap XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, f'sitemap-enriched-{page}.xml')
    
    # Якщо файл не існує, перенаправляємо на sitemap index
    if not os.path.exists(sitemap_path):
        return redirect(url_for('sitemap_index_xml'))
    
    return send_from_directory(os.path.dirname(sitemap_path), os.path.basename(sitemap_path), mimetype='application/xml')

@app.route('/sitemap-other-<int:page>.xml', endpoint='sitemap_other_xml')
def sitemap_other(page):
    """Serve pre-generated other sitemap XML"""
    sitemap_path = os.path.join(SITEMAP_DIR, f'sitemap-other-{page}.xml')
    
    # Якщо файл не існує, перенаправляємо на sitemap index
    if not os.path.exists(sitemap_path):
        return redirect(url_for('sitemap_index_xml'))
    
    return send_from_directory(os.path.dirname(sitemap_path), os.path.basename(sitemap_path), mimetype='application/xml')

# Налаштування планувальника задач для генерації sitemap
# Щоденна генерація для пріоритетних sitemap файлів
@scheduler.task('cron', id='generate_sitemap_daily', hour=2, minute=0)
def generate_sitemap_daily():
    """Щоденне оновлення priority, static і categories sitemap"""
    try:
        logging.info("Starting daily sitemap generation")
        generate_sitemap_static_file()
        generate_sitemap_categories_file()
        generate_sitemap_index_file()
        logging.info("Daily sitemap generation completed successfully")
    except Exception as e:
        logging.error(f"Error in daily sitemap generation: {e}", exc_info=True)

# Щотижнева генерація sitemap з товарами на складі
@scheduler.task('cron', id='generate_sitemap_weekly', day_of_week='mon', hour=3, minute=0)
def generate_sitemap_weekly():
    """Щотижневе оновлення stock sitemap файлів"""
    try:
        logging.info("Starting weekly stock sitemap generation")
        generate_sitemap_stock_files()
        generate_sitemap_index_file()
        logging.info("Weekly stock sitemap generation completed successfully")
    except Exception as e:
        logging.error(f"Error in weekly stock sitemap generation: {e}", exc_info=True)

# Щомісячна повна генерація всіх sitemap файлів
@scheduler.task('cron', id='generate_sitemap_monthly', month='1,4,7,10', day=1, hour=4, minute=0)
def generate_sitemap_monthly():
    """Щомісячна повна генерація всіх sitemap файлів (БЕЗ other файлів)"""
    try:
        logging.info("Starting monthly sitemap generation (quality focus)")
        generate_sitemap_static_file()
        generate_sitemap_categories_file()
        generate_sitemap_stock_files()
        generate_sitemap_enriched_files()  # Тільки якісні товари
        generate_sitemap_images_file()
        # generate_sitemap_other_files()  # ВИКЛЮЧЕНО
        generate_sitemap_index_file()
        logging.info("Monthly sitemap generation completed successfully")
    except Exception as e:
        logging.error(f"Error in monthly sitemap generation: {e}", exc_info=True)





# аналіз данних для потрапляння в сайтмап
@app.route('/<token>/admin/analyze-sitemap-data')
@requires_token_and_roles('admin')
@add_noindex_header
def analyze_sitemap_data(token):
    """
    Аналіз даних для sitemap (тільки якісні товари):
    """
    try:
        min_price = int(request.args.get('min_price', 100))
        max_price = int(request.args.get('max_price', 800))
        as_json = request.args.get('format') == 'json'

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SET statement_timeout = 90000")

        # ВИКЛЮЧАЄМО aftermarket і juaguar
        cursor.execute("SELECT table_name FROM price_lists WHERE table_name NOT IN ('stock', 'aftermarket', 'juaguar')")
        price_list_tables = [r[0] for r in cursor.fetchall()]
        
        if not price_list_tables:
            return ("<h1>No price list tables found</h1>" if not as_json
                    else jsonify({"error": "no_tables"}))

        per_table = []
        total_stock = 0
        total_enriched = 0

        # Аналіз stock
        cursor.execute("SELECT COUNT(*) FROM stock WHERE quantity > 0")
        total_stock = cursor.fetchone()[0] or 0

        # Аналіз enriched (з описами/фото) в ціновому діапазоні
        union_queries = []
        for table in price_list_tables:
            union_queries.append(f"SELECT article FROM {table} WHERE price BETWEEN {min_price} AND {max_price}")
        
        if union_queries:
            all_price_list_query = " UNION ALL ".join(union_queries)
            
            enriched_count_query = f"""
                SELECT COUNT(DISTINCT pl.article) 
                FROM ({all_price_list_query}) pl
                JOIN (
                    SELECT p.article FROM products p
                    UNION
                    SELECT pi.product_article FROM product_images pi
                ) AS enriched ON pl.article = enriched.article
                LEFT JOIN stock s ON pl.article = s.article
                WHERE s.article IS NULL
            """
            
            cursor.execute(enriched_count_query)
            total_enriched = cursor.fetchone()[0] or 0

        result_obj = {
            "params": {
                "min_price": min_price,
                "max_price": max_price,
                "excluded_tables": ["aftermarket", "juaguar"]
            },
            "tables_analyzed": len(price_list_tables),
            "totals": {
                "stock_items": total_stock,
                "enriched_items": total_enriched,
                "total_sitemap_urls": total_stock + total_enriched
            },
            "estimation": {
                "stock_files": max(1, math.ceil(total_stock / 10000)),
                "enriched_files": max(1, math.ceil(total_enriched / 10000)),
                "total_files": max(1, math.ceil(total_stock / 10000)) + max(1, math.ceil(total_enriched / 10000))
            },
            "quality_focus": "Only stock + products with descriptions/images included"
        }

        if as_json:
            return jsonify(result_obj)

        # HTML відповідь
        html = [
            "<h1>Quality Sitemap Analysis</h1>",
            f"<p>Focus: Stock + Enriched products only</p>",
            f"<p>Price range: {min_price}–{max_price} €</p>",
            f"<p>Excluded: aftermarket, juaguar</p>",
            f"<p><strong>Stock items:</strong> {total_stock:,}</p>",
            f"<p><strong>Enriched items:</strong> {total_enriched:,}</p>",
            f"<p><strong>Total URLs:</strong> {total_stock + total_enriched:,}</p>",
            f"<p><strong>Estimated files:</strong> {result_obj['estimation']['total_files']}</p>",
            "<p>✅ Much more manageable for Google indexing!</p>"
        ]

        return "".join(html)

    except Exception as e:
        logging.error(f"Error in analyze_sitemap_data: {e}", exc_info=True)
        return f"<h1>Error</h1><p>{e}</p>", 500





@app.route('/<token>/admin/run-scheduler-job', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_run_scheduler_job(token):
    """Запускає планувальник вручну"""
    try:
        job_id = request.form.get('job_id')
        if not job_id:
            flash("No job specified", "error")
            return redirect(url_for('admin_scheduler_status', token=token))
        
        # Знаходимо завдання за ID
        job_found = False
        for job in scheduler.get_jobs():
            if job.id == job_id:
                job_found = True
                break
                
        if not job_found:
            flash(f"Job '{job_id}' not found", "error")
            return redirect(url_for('admin_scheduler_status', token=token))
        
        # Запускаємо завдання в окремому потоці
        if job_id == 'generate_sitemap_daily':
            threading.Thread(target=generate_sitemap_daily).start()
        elif job_id == 'generate_sitemap_weekly':
            threading.Thread(target=generate_sitemap_weekly).start()
        elif job_id == 'generate_sitemap_monthly':
            threading.Thread(target=generate_sitemap_monthly).start()
        elif job_id == 'generate_sitemaps_distributed':
            threading.Thread(target=generate_sitemaps_distributed).start()
        else:
            flash(f"Unknown job ID: {job_id}", "error")
            return redirect(url_for('admin_scheduler_status', token=token))
        
        flash(f"Job '{job_id}' started successfully", "success")
        return redirect(url_for('admin_scheduler_status', token=token))
    
    except Exception as e:
        logging.error(f"Error running scheduler job: {e}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('admin_scheduler_status', token=token))

@app.route('/<token>/admin/scheduler-status')
@requires_token_and_roles('admin')
@add_noindex_header
def admin_scheduler_status(token):
    """Показує статус всіх запланованих завдань"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'next_run': job.next_run_time,
            'schedule': str(job.trigger)
        })
    return render_template('admin/scheduler_status.html', jobs=jobs, token=token)

@app.route('/<token>/admin/check-sitemap-data')
@requires_token_and_roles('admin')
@add_noindex_header
def admin_check_sitemap_data(token):
    """Діагностика стану бази даних для sitemap (тільки для адміністраторів)"""
    try:
        result = "<h1>Sitemap Data Diagnostic</h1>"
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Перевірка категорій
        cursor.execute("SELECT COUNT(*) FROM categories WHERE slug IS NOT NULL AND slug != ''")
        categories_count = cursor.fetchone()[0]
        result += f"<p>Categories with slug: {categories_count}</p>"
        
        # Перевірка товарів на складі
        cursor.execute("SELECT COUNT(*) FROM stock WHERE quantity > 0")
        stock_count = cursor.fetchone()[0]
        result += f"<p>Products in stock: {stock_count}</p>"
        
        # Перевірка таблиць прайс-листів
        cursor.execute("SELECT table_name FROM price_lists WHERE table_name != 'stock'")
        price_list_tables = [row[0] for row in cursor.fetchall()]
        
        result += f"<h2>Price Lists Tables ({len(price_list_tables)})</h2>"
        if price_list_tables:
            result += "<ul>"
            for table in price_list_tables:
                result += f"<li>{table}</li>"
            result += "</ul>"
        else:
            result += "<p>No price list tables found</p>"
            result += "<p><strong>This explains why enriched and other sitemaps are not generated</strong></p>"
        
        # Перевіряємо кількість товарів для різних типів sitemap
        if price_list_tables:
            # Формуємо динамічний SQL для запиту всіх товарів з прайс-листів
            union_queries = []
            for table in price_list_tables:
                union_queries.append(f"SELECT article, '{table}' AS source_table FROM {table}")
            
            all_price_list_query = " UNION ALL ".join(union_queries)
            
            # Рахуємо товари для enriched
            enriched_count_query = f"""
                SELECT COUNT(DISTINCT pl.article) 
                FROM ({all_price_list_query}) pl
                JOIN (
                    SELECT p.article FROM products p
                    UNION
                    SELECT pi.product_article FROM product_images pi
                ) AS enriched ON pl.article = enriched.article
                LEFT JOIN stock s ON pl.article = s.article
                WHERE s.article IS NULL
            """
            
            cursor.execute(enriched_count_query)
            enriched_count = cursor.fetchone()[0]
            result += f"<p>Enriched products: {enriched_count}</p>"
            
            # Рахуємо товари для other
            other_count_query = f"""
                SELECT COUNT(DISTINCT pl.article) 
                FROM ({all_price_list_query}) pl
                LEFT JOIN (
                    SELECT p.article FROM products p
                    UNION
                    SELECT pi.product_article FROM product_images pi
                ) AS enriched ON pl.article = enriched.article
                LEFT JOIN stock s ON pl.article = s.article
                WHERE s.article IS NULL AND enriched.article IS NULL
            """
            
            cursor.execute(other_count_query)
            other_count = cursor.fetchone()[0]
            result += f"<p>Other products: {other_count}</p>"
        
        # Перевіряємо стан файлів
        result += "<h2>Sitemap Files Status</h2>"
        if os.path.exists(SITEMAP_DIR):
            files = os.listdir(SITEMAP_DIR)
            result += f"<p>Files in directory ({len(files)}):</p><ul>"
            for file in files:
                file_path = os.path.join(SITEMAP_DIR, file)
                file_size = os.path.getsize(file_path) / 1024  # KB
                result += f"<li>{file} - {file_size:.2f} KB</li>"
            result += "</ul>"
        else:
            result += "<p>Directory does not exist</p>"
            
        cursor.close()
        conn.close()
        
        return result
    except Exception as e:
        logging.error(f"Error in admin_check_sitemap_data: {e}", exc_info=True)
        return f"<h1>Error</h1><p>{str(e)}</p>"

# Перенаправлення публічної діагностики на адмін-версію
@app.route('/check-sitemap-data')
def check_sitemap_data():
    """Публічний доступ до діагностики sitemap перенаправляється на вхід для адміністраторів"""
    if 'user_id' in session and validate_token(request.args.get('token')):
        # Якщо користувач авторизований і має токен, спробуємо перенаправити на адмін-версію
        return redirect(url_for('admin_check_sitemap_data', token=request.args.get('token')))
    else:
        # Інакше відмовляємо в доступі
        return "Access denied. You need to be logged in as an administrator.", 403

@app.route('/<token>/admin/sitemap-utils')
@requires_token_and_roles('admin')
@add_noindex_header
def admin_sitemap_utils(token):
    """Утиліти для роботи з sitemap-файлами"""
    try:
        # Перевіряємо відповідність файлів в індексі з реальними файлами
        index_files = []
        missing_files = []
        
        if os.path.exists(os.path.join(SITEMAP_DIR, 'sitemap-index.xml')):
            with open(os.path.join(SITEMAP_DIR, 'sitemap-index.xml'), 'r', encoding='utf-8') as f:
                index_content = f.read()
                
            # Парсимо XML за допомогою регулярних виразів
            import re
            loc_pattern = r'<loc>(.*?)</loc>'
            locations = re.findall(loc_pattern, index_content)
            
            for loc in locations:
                file_name = loc.split('/')[-1]
                index_files.append(file_name)
                
                if not os.path.exists(os.path.join(SITEMAP_DIR, file_name)):
                    missing_files.append(file_name)
        
        return render_template(
            'admin/sitemaps/sitemap_utils.html',
            token=token,
            index_files=index_files,
            missing_files=missing_files
        )
    except Exception as e:
        logging.error(f"Error in admin_sitemap_utils: {e}", exc_info=True)
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('admin_sitemaps', token=token))


# Список всіх статей з фільтрацією
@app.route('/<token>/admin/blog', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_blog_posts(token):
    try:
        status_filter = request.args.get('status', '')
        category_filter = request.args.get('category', '')
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Base query
            query = """
                SELECT 
                    bp.id, 
                    bp.slug,
                    bp.published, 
                    bp.published_at,
                    bp.views,
                    bpt_sk.title as title_sk,
                    bpt_en.title as title_en,
                    bpt_pl.title as title_pl,
                    bpt_hu.title as title_hu,
                    array_agg(DISTINCT bct.name) as categories
                FROM blog_posts bp
                LEFT JOIN blog_post_translations bpt_sk ON bp.id = bpt_sk.post_id AND bpt_sk.language = 'sk'
                LEFT JOIN blog_post_translations bpt_en ON bp.id = bpt_en.post_id AND bpt_en.language = 'en'
                LEFT JOIN blog_post_translations bpt_pl ON bp.id = bpt_pl.post_id AND bpt_pl.language = 'pl'
                LEFT JOIN blog_post_translations bpt_hu ON bp.id = bpt_hu.post_id AND bpt_hu.language = 'hu'
                LEFT JOIN blog_post_categories bpc ON bp.id = bpc.post_id
                LEFT JOIN blog_categories bc ON bpc.category_id = bc.id
                LEFT JOIN blog_category_translations bct ON bc.id = bct.category_id AND bct.language = 'sk'
            """
            
            # Filter conditions
            conditions = []
            params = []
            
            if status_filter:
                if status_filter == 'published':
                    conditions.append("bp.published = TRUE")
                elif status_filter == 'draft':
                    conditions.append("bp.published = FALSE")
            
            if category_filter:
                conditions.append("bc.id = %s")
                params.append(category_filter)
            
            # Add conditions to query
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
                
            # Grouping and sorting
            query += " GROUP BY bp.id, bp.slug, bp.published, bp.published_at, bp.views, bpt_sk.title, bpt_en.title, bpt_pl.title, bpt_hu.title ORDER BY bp.published_at DESC"
            
            cursor.execute(query, params)
            posts = cursor.fetchall()
            
            # Get categories for filter
            cursor.execute("""
                SELECT bc.id, bct.name
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id 
                WHERE bct.language = 'sk'
                ORDER BY bct.name
            """)
            categories = cursor.fetchall()
            
            return render_template(
                'admin/blog/posts_list.html',
                token=token,
                posts=posts,
                categories=categories,
                status_filter=status_filter,
                category_filter=category_filter
            )
            
    except Exception as e:
        logging.error(f"Error in admin_blog_posts: {e}", exc_info=True)
        flash("Error loading blog posts", "error")
        return redirect(url_for('admin_dashboard', token=token)) 


@app.route('/blog/')
@app.route('/blog')
def blog_index():
    try:
        # Get parameters
        lang = session.get('language', app.config['BABEL_DEFAULT_LOCALE'])
        page = request.args.get('page', 1, type=int)
        category_slug = request.args.get('category', '')
        per_page = 10
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Base query
            query = """
                SELECT 
                    bp.id,
                    bp.slug,
                    bp.featured_image,
                    bp.published_at,
                    bpt.title,
                    bpt.excerpt,
                    bp.views,
                    array_agg(DISTINCT bct.name) as categories
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                LEFT JOIN blog_post_categories bpc ON bp.id = bpc.post_id
                LEFT JOIN blog_categories bc ON bpc.category_id = bc.id
                LEFT JOIN blog_category_translations bct ON bc.id = bct.category_id AND bct.language = %s
                WHERE bp.published = TRUE
            """
            
            params = [lang, lang]
            
            # Apply category filter if needed
            if category_slug:
                query += " AND EXISTS (SELECT 1 FROM blog_post_categories bpc2 JOIN blog_categories bc2 ON bpc2.category_id = bc2.id WHERE bpc2.post_id = bp.id AND bc2.slug = %s)"
                params.append(category_slug)
            
            # Complete query with grouping and order
            query += """
                GROUP BY 
                    bp.id,
                    bp.slug,
                    bp.featured_image,
                    bp.published_at,
                    bpt.title,
                    bpt.excerpt,
                    bp.views
                ORDER BY bp.published_at DESC
                LIMIT %s OFFSET %s
            """
            params.extend([per_page, (page - 1) * per_page])
            
            # Get the count of posts (for pagination)
            count_query = """
                SELECT COUNT(DISTINCT bp.id)
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                WHERE bp.published = TRUE
            """
            
            count_params = [lang]
            
            if category_slug:
                count_query += " AND EXISTS (SELECT 1 FROM blog_post_categories bpc JOIN blog_categories bc ON bpc.category_id = bc.id WHERE bpc.post_id = bp.id AND bc.slug = %s)"
                count_params.append(category_slug)
            
            cursor.execute(count_query, count_params)
            total_posts = cursor.fetchone()[0] or 0  # Use 0 if None
            
            if total_posts > 0:
                # Get the posts
                cursor.execute(query, params)
                posts = cursor.fetchall()
            else:
                posts = []  # No posts found
            
            # Get categories for the sidebar - always try to show categories if they exist
            cursor.execute("""
                SELECT 
                    bc.slug,
                    bct.name,
                    COUNT(DISTINCT bp.id) as post_count
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id AND bct.language = %s
                LEFT JOIN blog_post_categories bpc ON bc.id = bpc.category_id
                LEFT JOIN blog_posts bp ON bpc.post_id = bp.id AND bp.published = TRUE
                GROUP BY bc.slug, bct.name
                HAVING COUNT(DISTINCT bp.id) > 0
                ORDER BY bct.name
            """, [lang])
            
            categories = cursor.fetchall()
            
            # Get recent posts for sidebar
            cursor.execute("""
                SELECT 
                    bp.slug,
                    bpt.title,
                    bp.published_at
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                WHERE bp.published = TRUE
                ORDER BY bp.published_at DESC
                LIMIT 5
            """, [lang])
            
            recent_posts = cursor.fetchall()
            
            # Calculate total pages
            total_pages = (total_posts + per_page - 1) // per_page if total_posts > 0 else 1
            
            # Get selected category name if filtering
            selected_category = None
            if category_slug:
                cursor.execute("""
                    SELECT bct.name 
                    FROM blog_categories bc
                    JOIN blog_category_translations bct ON bc.id = bct.category_id AND bct.language = %s
                    WHERE bc.slug = %s
                """, [lang, category_slug])
                
                category_result = cursor.fetchone()
                if category_result:
                    selected_category = category_result[0]
            
            return render_template(
                'public/blog/index.html',
                posts=posts,
                total_posts=total_posts,
                page=page,
                total_pages=total_pages,
                categories=categories or [],  # Ensure it's never None
                recent_posts=recent_posts or [],  # Ensure it's never None
                selected_category=selected_category,
                category_slug=category_slug,
                lang=lang
            )
            
    except Exception as e:
        logging.error(f"Error in blog_index: {e}", exc_info=True)
        flash(_("An error occurred while loading blog posts"), "error")
        return redirect(url_for('index'))


# Add this route near your other admin routes
@app.route('/<token>/admin/generate-slug', methods=['POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_generate_slug(token):
    """Generate a SEO-friendly slug from provided text"""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'No text provided'}), 400
            
        text = data.get('text', '').strip()
        lang = data.get('lang', 'en')
        
        if not text:
            return jsonify({'error': 'Empty text provided'}), 400
            
        slug = generate_slug(text, lang)
        return jsonify({'slug': slug})
    except Exception as e:
        logging.error(f"Error generating slug: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
# Створення нової статті
@app.route('/<token>/admin/blog/create', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_create_blog_post(token):
    if request.method == 'POST':
        try:
            slug = request.form.get('slug', '').strip()
            featured_image = request.form.get('featured_image', '')
            published = request.form.get('published') == 'on'
            
            # Якщо slug не вказано, генеруємо з title_sk
            if not slug:
                title_sk = request.form.get('title_sk', '').strip()
                slug = generate_slug(title_sk, 'sk')
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Створюємо запис у головній таблиці
                cursor.execute("""
                    INSERT INTO blog_posts 
                    (slug, author_id, featured_image, published, published_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id
                """, (
                    slug, 
                    session.get('user_id'), 
                    featured_image, 
                    published,
                    datetime.now() if published else None
                ))
                
                post_id = cursor.fetchone()[0]
                
                # Створюємо переклади для всіх мов
                languages = ['sk', 'en', 'pl', 'hu']
                
                for lang in languages:
                    title = request.form.get(f'title_{lang}', '').strip()
                    excerpt = request.form.get(f'excerpt_{lang}', '').strip()
                    content = request.form.get(f'content_{lang}', '').strip()
                    meta_title = request.form.get(f'meta_title_{lang}', '').strip()
                    meta_description = request.form.get(f'meta_description_{lang}', '').strip()
                    
                    # Якщо переклад для мови не надано, пропускаємо
                    if not title and not content:
                        continue
                        
                    cursor.execute("""
                        INSERT INTO blog_post_translations 
                        (post_id, language, title, excerpt, content, meta_title, meta_description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        post_id, 
                        lang, 
                        title, 
                        excerpt, 
                        content, 
                        meta_title or title, 
                        meta_description or excerpt
                    ))
                
                # Зберігаємо зв'язки з категоріями
                categories = request.form.getlist('categories')
                for category_id in categories:
                    cursor.execute("""
                        INSERT INTO blog_post_categories 
                        (post_id, category_id)
                        VALUES (%s, %s)
                    """, (post_id, category_id))
                
                # Зберігаємо зв'язки з тегами
                tags = request.form.get('tags', '').strip().split(',')
                for tag_name in tags:
                    tag_name = tag_name.strip()
                    if not tag_name:
                        continue
                        
                    # Шукаємо тег або створюємо новий
                    cursor.execute("SELECT id FROM blog_tags WHERE slug = %s", (generate_slug(tag_name),))
                    tag_row = cursor.fetchone()
                    
                    if tag_row:
                        tag_id = tag_row[0]
                    else:
                        cursor.execute("""
                            INSERT INTO blog_tags (slug) 
                            VALUES (%s) 
                            RETURNING id
                        """, (generate_slug(tag_name),))
                        tag_id = cursor.fetchone()[0]
                        
                        # Створюємо переклади тегу
                        for lang in languages:
                            cursor.execute("""
                                INSERT INTO blog_tag_translations 
                                (tag_id, language, name)
                                VALUES (%s, %s, %s)
                            """, (tag_id, lang, tag_name))
                    
                    # Створюємо зв'язок
                    cursor.execute("""
                        INSERT INTO blog_post_tags 
                        (post_id, tag_id)
                        VALUES (%s, %s)
                    """, (post_id, tag_id))
                
                conn.commit()
                flash("Blog post created successfully", "success")
                return redirect(url_for('admin_edit_blog_post', token=token, post_id=post_id))
                
        except Exception as e:
            logging.error(f"Error creating blog post: {e}", exc_info=True)
            flash(f"Error creating blog post: {str(e)}", "error")
    
    # GET запит - відображаємо форму
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо категорії для вибору
            cursor.execute("""
                SELECT bc.id, bct.name
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id 
                WHERE bct.language = 'sk'
                ORDER BY bct.name
            """)
            categories = cursor.fetchall()
            
            # Створюємо словник доступних мов для шаблону
            supported_languages = {
                'sk': 'Slovenčina',
                'en': 'English',
                'pl': 'Polski',
                'hu': 'Magyar'
            }
            
            return render_template(
                'admin/blog/post_form.html',
                token=token,
                post=None,
                categories=categories,
                supported_languages=supported_languages,
                mode='create'
            )
            
    except Exception as e:
        logging.error(f"Error in admin_create_blog_post: {e}", exc_info=True)
        flash("Error loading form", "error")
        return redirect(url_for('admin_blog_posts', token=token))

# Редагування статті
@app.route('/<token>/admin/blog/edit/<int:post_id>', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_edit_blog_post(token, post_id):
    if request.method == 'POST':
        try:
            slug = request.form.get('slug', '').strip()
            featured_image = request.form.get('featured_image', '')
            published = request.form.get('published') == 'on'
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Оновлюємо головний запис
                cursor.execute("""
                    UPDATE blog_posts
                    SET slug = %s,
                        featured_image = %s,
                        published = %s,
                        published_at = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    slug,
                    featured_image,
                    published,
                    datetime.now() if published else None,
                    post_id
                ))
                
                # Оновлюємо переклади
                languages = ['sk', 'en', 'pl', 'hu']
                
                for lang in languages:
                    title = request.form.get(f'title_{lang}', '').strip()
                    excerpt = request.form.get(f'excerpt_{lang}', '').strip()
                    content = request.form.get(f'content_{lang}', '').strip()
                    meta_title = request.form.get(f'meta_title_{lang}', '').strip()
                    meta_description = request.form.get(f'meta_description_{lang}', '').strip()
                    
                    # Перевіряємо, чи існує вже переклад для цієї мови
                    cursor.execute("""
                        SELECT id FROM blog_post_translations
                        WHERE post_id = %s AND language = %s
                    """, (post_id, lang))
                    
                    translation_exists = cursor.fetchone()
                    
                    if translation_exists:
                        # Якщо не вказано ні заголовок, ні контент - видаляємо переклад
                        if not title and not content:
                            cursor.execute("""
                                DELETE FROM blog_post_translations
                                WHERE post_id = %s AND language = %s
                            """, (post_id, lang))
                        else:
                            # Інакше - оновлюємо
                            cursor.execute("""
                                UPDATE blog_post_translations
                                SET title = %s,
                                    excerpt = %s,
                                    content = %s,
                                    meta_title = %s,
                                    meta_description = %s
                                WHERE post_id = %s AND language = %s
                            """, (
                                title,
                                excerpt,
                                content,
                                meta_title or title,
                                meta_description or excerpt,
                                post_id,
                                lang
                            ))
                    else:
                        # Якщо не існує і є хоча б заголовок або контент - створюємо
                        if title or content:
                            cursor.execute("""
                                INSERT INTO blog_post_translations
                                (post_id, language, title, excerpt, content, meta_title, meta_description)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (
                                post_id,
                                lang,
                                title,
                                excerpt,
                                content,
                                meta_title or title,
                                meta_description or excerpt
                            ))
                
                # Оновлюємо зв'язки з категоріями
                cursor.execute("DELETE FROM blog_post_categories WHERE post_id = %s", (post_id,))
                categories = request.form.getlist('categories')
                for category_id in categories:
                    cursor.execute("""
                        INSERT INTO blog_post_categories 
                        (post_id, category_id)
                        VALUES (%s, %s)
                    """, (post_id, category_id))
                
                # Оновлюємо зв'язки з тегами
                cursor.execute("DELETE FROM blog_post_tags WHERE post_id = %s", (post_id,))
                tags = request.form.get('tags', '').strip().split(',')
                for tag_name in tags:
                    tag_name = tag_name.strip()
                    if not tag_name:
                        continue
                        
                    # Шукаємо тег або створюємо новий
                    cursor.execute("SELECT id FROM blog_tags WHERE slug = %s", (generate_slug(tag_name),))
                    tag_row = cursor.fetchone()
                    
                    if tag_row:
                        tag_id = tag_row[0]
                    else:
                        cursor.execute("""
                            INSERT INTO blog_tags (slug) 
                            VALUES (%s) 
                            RETURNING id
                        """, (generate_slug(tag_name),))
                        tag_id = cursor.fetchone()[0]
                        
                        # Створюємо переклади тегу
                        for lang in languages:
                            cursor.execute("""
                                INSERT INTO blog_tag_translations 
                                (tag_id, language, name)
                                VALUES (%s, %s, %s)
                            """, (tag_id, lang, tag_name))
                    
                    # Створюємо зв'язок
                    cursor.execute("""
                        INSERT INTO blog_post_tags 
                        (post_id, tag_id)
                        VALUES (%s, %s)
                    """, (post_id, tag_id))
                
                conn.commit()
                flash("Blog post updated successfully", "success")
                return redirect(url_for('admin_blog_posts', token=token))
                
        except Exception as e:
            logging.error(f"Error updating blog post: {e}", exc_info=True)
            flash(f"Error updating blog post: {str(e)}", "error")
    
    # GET запит - завантажуємо дані для форми
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо основні дані посту
            cursor.execute("""
                SELECT * FROM blog_posts WHERE id = %s
            """, (post_id,))
            post = cursor.fetchone()
            
            if not post:
                flash("Blog post not found", "error")
                return redirect(url_for('admin_blog_posts', token=token))
            
            # Отримуємо переклади
            cursor.execute("""
                SELECT * FROM blog_post_translations WHERE post_id = %s
            """, (post_id,))
            translations = cursor.fetchall()
            
            # Перетворюємо у словник перекладів по мовах
            post_translations = {}
            for translation in translations:
                post_translations[translation['language']] = dict(translation)
            
            # Отримуємо категорії для вибору
            cursor.execute("""
                SELECT bc.id, bct.name
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id 
                WHERE bct.language = 'sk'
                ORDER BY bct.name
            """)
            all_categories = cursor.fetchall()
            
            # Отримуємо вибрані категорії
            cursor.execute("""
                SELECT category_id FROM blog_post_categories WHERE post_id = %s
            """, (post_id,))
            selected_categories = [row[0] for row in cursor.fetchall()]
            
            # Отримуємо теги
            cursor.execute("""
                SELECT bt.id, btt.name
                FROM blog_post_tags bpt
                JOIN blog_tags bt ON bpt.tag_id = bt.id
                JOIN blog_tag_translations btt ON bt.id = btt.tag_id
                WHERE bpt.post_id = %s AND btt.language = 'sk'
            """, (post_id,))
            tags = cursor.fetchall()
            tags_string = ', '.join(row[1] for row in tags)
            
            # Створюємо словник доступних мов для шаблону
            supported_languages = {
                'sk': 'Slovenčina',
                'en': 'English',
                'pl': 'Polski',
                'hu': 'Magyar'
            }
            
            return render_template(
                'admin/blog/post_form.html',
                token=token,
                post=post,
                post_translations=post_translations,
                categories=all_categories,
                selected_categories=selected_categories,
                tags=tags_string,
                supported_languages=supported_languages,
                mode='edit'
            )
            
    except Exception as e:
        logging.error(f"Error loading blog post for edit: {e}", exc_info=True)
        flash("Error loading blog post", "error")
        return redirect(url_for('admin_blog_posts', token=token))

# Видалення статті
@app.route('/<token>/admin/blog/delete/<int:post_id>', methods=['POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_delete_blog_post(token, post_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Видаляємо всі пов'язані записи
            cursor.execute("DELETE FROM blog_post_tags WHERE post_id = %s", (post_id,))
            cursor.execute("DELETE FROM blog_post_categories WHERE post_id = %s", (post_id,))
            cursor.execute("DELETE FROM blog_post_translations WHERE post_id = %s", (post_id,))
            cursor.execute("DELETE FROM blog_posts WHERE id = %s", (post_id,))
            
            conn.commit()
            flash("Blog post deleted successfully", "success")
            
    except Exception as e:
        logging.error(f"Error deleting blog post: {e}", exc_info=True)
        flash(f"Error deleting blog post: {str(e)}", "error")
        
    return redirect(url_for('admin_blog_posts', token=token))

# Управління категоріями блогу
@app.route('/<token>/admin/blog/categories', methods=['GET', 'POST'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_blog_categories(token):
    # Обробка POST запиту на створення або оновлення категорії
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            
            if action == 'create':
                # Створення нової категорії
                slug = request.form.get('slug', '').strip()
                name_sk = request.form.get('name_sk', '').strip()
                
                # Якщо slug не вказано, генеруємо з імені категорії
                if not slug and name_sk:
                    slug = generate_slug(name_sk)
                
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Створюємо запис категорії
                    cursor.execute("""
                        INSERT INTO blog_categories (slug, created_at, updated_at)
                        VALUES (%s, NOW(), NOW())
                        RETURNING id
                    """, (slug,))
                    
                    category_id = cursor.fetchone()[0]
                    
                    # Додаємо переклади для всіх мов
                    languages = ['sk', 'en', 'pl', 'hu']
                    
                    for lang in languages:
                        name = request.form.get(f'name_{lang}', '').strip()
                        description = request.form.get(f'description_{lang}', '').strip()
                        
                        # Якщо переклад не надано, пропускаємо
                        if not name:
                            continue
                            
                        cursor.execute("""
                            INSERT INTO blog_category_translations
                            (category_id, language, name, description)
                            VALUES (%s, %s, %s, %s)
                        """, (category_id, lang, name, description))
                    
                    conn.commit()
                    flash("Category created successfully", "success")
                    
            elif action == 'update':
                # Оновлення існуючої категорії
                category_id = request.form.get('category_id')
                slug = request.form.get('slug', '').strip()
                
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Оновлюємо запис категорії
                    cursor.execute("""
                        UPDATE blog_categories
                        SET slug = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (slug, category_id))
                    
                    # Оновлюємо переклади
                    languages = ['sk', 'en', 'pl', 'hu']
                    
                    for lang in languages:
                        name = request.form.get(f'name_{lang}', '').strip()
                        description = request.form.get(f'description_{lang}', '').strip()
                        
                        cursor.execute("""
                            SELECT id FROM blog_category_translations
                            WHERE category_id = %s AND language = %s
                        """, (category_id, lang))
                        
                        translation_exists = cursor.fetchone()
                        
                        if translation_exists:
                            if name:
                                cursor.execute("""
                                    UPDATE blog_category_translations
                                    SET name = %s, description = %s
                                    WHERE category_id = %s AND language = %s
                                """, (name, description, category_id, lang))
                            else:
                                cursor.execute("""
                                    DELETE FROM blog_category_translations
                                    WHERE category_id = %s AND language = %s
                                """, (category_id, lang))
                        elif name:
                            cursor.execute("""
                                INSERT INTO blog_category_translations
                                (category_id, language, name, description)
                                VALUES (%s, %s, %s, %s)
                            """, (category_id, lang, name, description))
                    
                    conn.commit()
                    flash("Category updated successfully", "success")
                    
            elif action == 'delete':
                # Видалення категорії
                category_id = request.form.get('category_id')
                
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Перевіряємо, чи є статті з цією категорією
                    cursor.execute("""
                        SELECT COUNT(*) FROM blog_post_categories
                        WHERE category_id = %s
                    """, (category_id,))
                    
                    if cursor.fetchone()[0] > 0:
                        flash("Cannot delete category with associated posts", "error")
                    else:
                        # Видаляємо переклади та саму категорію
                        cursor.execute("""
                            DELETE FROM blog_category_translations
                            WHERE category_id = %s
                        """, (category_id,))
                        
                        cursor.execute("""
                            DELETE FROM blog_categories
                            WHERE id = %s
                        """, (category_id,))
                        
                        conn.commit()
                        flash("Category deleted successfully", "success")
        
        except Exception as e:
            logging.error(f"Error in admin_blog_categories: {e}", exc_info=True)
            flash(f"Error processing category: {str(e)}", "error")
        
        return redirect(url_for('admin_blog_categories', token=token))
    
    # GET запит - відображення списку категорій
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо всі категорії з перекладами
            cursor.execute("""
                SELECT 
                    bc.id,
                    bc.slug,
                    bc.created_at,
                    bc.updated_at,
                    COALESCE(sk.name, '') as name_sk,
                    COALESCE(en.name, '') as name_en,
                    COALESCE(pl.name, '') as name_pl,
                    COALESCE(hu.name, '') as name_hu,
                    (SELECT COUNT(*) FROM blog_post_categories WHERE category_id = bc.id) as post_count
                FROM blog_categories bc
                LEFT JOIN blog_category_translations sk ON bc.id = sk.category_id AND sk.language = 'sk'
                LEFT JOIN blog_category_translations en ON bc.id = en.category_id AND en.language = 'en'
                LEFT JOIN blog_category_translations pl ON bc.id = pl.category_id AND pl.language = 'pl'
                LEFT JOIN blog_category_translations hu ON bc.id = hu.category_id AND hu.language = 'hu'
                ORDER BY bc.created_at DESC
            """)
            
            categories = cursor.fetchall()
            
            # Створюємо словник доступних мов для шаблону
            supported_languages = {
                'sk': 'Slovenčina',
                'en': 'English',
                'pl': 'Polski',
                'hu': 'Magyar'
            }
            
            return render_template(
                'admin/blog/categories.html',
                token=token,
                categories=categories,
                supported_languages=supported_languages
            )
            
    except Exception as e:
        logging.error(f"Error loading blog categories: {e}", exc_info=True)
        flash("Error loading categories", "error")
        return redirect(url_for('admin_dashboard', token=token))

# Статистика блогу
@app.route('/<token>/admin/blog/statistics', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_blog_statistics(token):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Загальна кількість постів
            cursor.execute("SELECT COUNT(*) FROM blog_posts")
            total_posts = cursor.fetchone()[0]
            
            # Опубліковані пости
            cursor.execute("SELECT COUNT(*) FROM blog_posts WHERE published = TRUE")
            published_posts = cursor.fetchone()[0]
            
            # Недавно додані пости (за останній місяць)
            cursor.execute("SELECT COUNT(*) FROM blog_posts WHERE created_at >= NOW() - INTERVAL '1 month'")
            recent_posts = cursor.fetchone()[0]
            
            # Загальна кількість переглядів
            cursor.execute("SELECT SUM(views) FROM blog_posts")
            total_views = cursor.fetchone()[0] or 0
            
            # Найпопулярніші пости
            cursor.execute("""
                SELECT 
                    bp.id,
                    bp.slug,
                    bp.views,
                    bpt.title
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = 'sk'
                ORDER BY bp.views DESC
                LIMIT 10
            """)
            popular_posts = cursor.fetchall()
            
            # Статистика по категоріях
            cursor.execute("""
                SELECT 
                    bc.id,
                    bct.name,
                    COUNT(bpc.post_id) as post_count
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id AND bct.language = 'sk'
                LEFT JOIN blog_post_categories bpc ON bc.id = bpc.category_id
                GROUP BY bc.id, bct.name
                ORDER BY post_count DESC
            """)
            category_stats = cursor.fetchall()
            
            # Статистика по мовах
            cursor.execute("""
                SELECT 
                    language,
                    COUNT(DISTINCT post_id) as post_count
                FROM blog_post_translations
                GROUP BY language
                ORDER BY post_count DESC
            """)
            language_stats = cursor.fetchall()
            
            return render_template(
                'admin/blog/statistics.html',
                token=token,
                total_posts=total_posts,
                published_posts=published_posts,
                recent_posts=recent_posts,
                total_views=total_views,
                popular_posts=popular_posts,
                category_stats=category_stats,
                language_stats=language_stats
            )
            
    except Exception as e:
        logging.error(f"Error in admin_blog_statistics: {e}", exc_info=True)
        flash("Error loading blog statistics", "error")
        return redirect(url_for('admin_blog_posts', token=token))




# Сторінка окремої статті блогу
@app.route('/blog/<slug>', methods=['GET'])
def blog_post(slug):
    try:
        # Визначення поточної мови
        lang = session.get('language', app.config['BABEL_DEFAULT_LOCALE'])
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо дані статті
            cursor.execute("""
                SELECT 
                    bp.id,
                    bp.slug,
                    bp.featured_image,
                    bp.published_at,
                    bp.views,
                    bp.reading_time,
                    bpt.title,
                    bpt.content,
                    bpt.excerpt,
                    bpt.meta_title,
                    bpt.meta_description
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                WHERE bp.slug = %s AND bp.published = TRUE
            """, [lang, slug])
            
            post = cursor.fetchone()
            
            if not post:
                flash(_("Article not found"), "error")
                return redirect(url_for('blog_index'))
            
            # Отримання категорій статті
            cursor.execute("""
                SELECT bc.slug, bct.name
                FROM blog_categories bc
                JOIN blog_post_categories bpc ON bc.id = bpc.category_id
                JOIN blog_category_translations bct ON bc.id = bct.category_id AND bct.language = %s
                WHERE bpc.post_id = %s
            """, [lang, post['id']])
            
            categories = cursor.fetchall()
            
            # Отримання тегів статті
            cursor.execute("""
                SELECT bt.slug, btt.name
                FROM blog_tags bt
                JOIN blog_post_tags bpt ON bt.id = bpt.tag_id
                JOIN blog_tag_translations btt ON bt.id = btt.tag_id AND btt.language = %s
                WHERE bpt.post_id = %s
            """, [lang, post['id']])
            
            tags = cursor.fetchall()
            
            # Отримуємо пов'язані статті (за категоріями) - ВИПРАВЛЕНО SQL
            cursor.execute("""
                SELECT 
                    bp.id,
                    bp.slug,
                    bp.featured_image,
                    bpt.title,
                    bpt.excerpt,
                    bp.published_at
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                JOIN blog_post_categories bpc ON bp.id = bpc.post_id
                WHERE bp.published = TRUE
                AND bpc.category_id IN (
                    SELECT category_id 
                    FROM blog_post_categories 
                    WHERE post_id = %s
                )
                AND bp.id != %s
                GROUP BY bp.id, bp.slug, bp.featured_image, bpt.title, bpt.excerpt, bp.published_at
                ORDER BY bp.published_at DESC
                LIMIT 3
            """, [lang, post['id'], post['id']])
            
            related_posts = cursor.fetchall()
            
            # Оновлюємо лічильник переглядів
            cursor.execute("""
                UPDATE blog_posts SET views = views + 1 WHERE id = %s
            """, [post['id']])
            conn.commit()
            
            return render_template(
                'public/blog/post.html',
                post=post,
                categories=categories,
                tags=tags,
                related_posts=related_posts,
                full_uri=request.url,
                lang=lang
            )
            
    except Exception as e:
        logging.error(f"Error in blog_post: {e}", exc_info=True)
        flash(_("An error occurred while loading the article"), "error")
        return redirect(url_for('blog_index'))

# Сторінка категорії блогу
@app.route('/blog/category/<slug>', methods=['GET'])
def blog_category(slug):
    # Перенаправляємо на головну сторінку блогу з параметром категорії
    return redirect(url_for('blog_index', category=slug))

# Сторінка тегу блогу
@app.route('/blog/tag/<slug>', methods=['GET'])
def blog_tag(slug):
    # Перенаправляємо на головну сторінку блогу з параметром тега
    return redirect(url_for('blog_index', tag=slug))

# Оптимізоване відображення зображень блогу
@app.route('/blog/image/<path:filename>')
def blog_image(filename):
    # Обробка зображень з кешуванням
    return send_from_directory('static/blog/images', filename, max_age=31536000)  # 1 рік кешування


def generate_sitemap_blog_file():
    """Генерує sitemap файл для блогу і зберігає на диск"""
    try:
        logging.info("Starting blog sitemap generation")
        base_url = os.getenv('BASE_URL', 'https://autogroup.sk')
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Отримуємо всі опубліковані статті з усіма доступними перекладами
            cursor.execute("""
                SELECT DISTINCT
                    bp.id,
                    bp.slug,
                    bp.updated_at,
                    array_agg(DISTINCT bpt.language) as languages
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id
                WHERE bp.published = TRUE
                GROUP BY bp.id, bp.slug, bp.updated_at
                ORDER BY bp.updated_at DESC
            """)
            
            posts = cursor.fetchall()
            
            # Отримуємо всі категорії блогу з усіма доступними перекладами
            cursor.execute("""
                SELECT DISTINCT
                    bc.id,
                    bc.slug,
                    bc.updated_at,
                    array_agg(DISTINCT bct.language) as languages
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id
                JOIN blog_post_categories bpc ON bc.id = bpc.category_id
                JOIN blog_posts bp ON bpc.post_id = bp.id
                WHERE bp.published = TRUE
                GROUP BY bc.id, bc.slug, bc.updated_at
                ORDER BY bc.updated_at DESC
            """)
            
            categories = cursor.fetchall()
            
            # Отримуємо всі теги блогу з усіма доступними перекладами
            cursor.execute("""
                SELECT DISTINCT
                    bt.id,
                    bt.slug,
                    array_agg(DISTINCT btt.language) as languages
                FROM blog_tags bt
                JOIN blog_tag_translations btt ON bt.id = btt.tag_id
                JOIN blog_post_tags bpt ON bt.id = bpt.tag_id
                JOIN blog_posts bp ON bpt.post_id = bp.id
                WHERE bp.published = TRUE
                GROUP BY bt.id, bt.slug
                ORDER BY bt.id
            """)
            
            tags = cursor.fetchall()
        
        # Створюємо sitemap-blog.xml
        sitemap_path = os.path.join(SITEMAP_DIR, 'sitemap-blog.xml')
        
        # Визначаємо URL-и для sitemap
        urls = []
        
        # Додаємо головну сторінку блогу з усіма мовними версіями
        for lang in app.config['BABEL_SUPPORTED_LOCALES']:
            urls.append({
                'loc': f"{base_url}/blog?lang_code={lang}",
                'changefreq': 'daily',
                'priority': '0.8'
            })
        
        # Додаємо сторінки статей блогу
        for post in posts:
            for lang in post['languages']:
                urls.append({
                    'loc': f"{base_url}/blog/{post['slug']}?lang_code={lang}",
                    'lastmod': post['updated_at'].strftime('%Y-%m-%d'),
                    'changefreq': 'weekly',
                    'priority': '0.7'
                })
        
        # Додаємо сторінки категорій
        for category in categories:
            for lang in category['languages']:
                urls.append({
                    'loc': f"{base_url}/blog/category/{category['slug']}?lang_code={lang}",
                    'changefreq': 'weekly',
                    'priority': '0.6'
                })
        
        # Додаємо сторінки тегів
        for tag in tags:
            for lang in tag['languages']:
                urls.append({
                    'loc': f"{base_url}/blog/tag/{tag['slug']}?lang_code={lang}",
                    'changefreq': 'weekly',
                    'priority': '0.5'
                })
        
        # Створюємо XML-контент
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        
        for url in urls:
            xml_content += '  <url>\n'
            xml_content += f'    <loc>{url["loc"]}</loc>\n'
            if 'lastmod' in url:
                xml_content += f'    <lastmod>{url["lastmod"]}</lastmod>\n'
            if 'changefreq' in url:
                xml_content += f'    <changefreq>{url["changefreq"]}</changefreq>\n'
            if 'priority' in url:
                xml_content += f'    <priority>{url["priority"]}</priority>\n'
            xml_content += '  </url>\n'
        
        xml_content += '</urlset>'
        
        # Записуємо файл
        with open(sitemap_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        
        logging.info(f"Blog sitemap generated successfully: {sitemap_path}")
        return True
        
    except Exception as e:
        logging.error(f"Error generating blog sitemap: {e}", exc_info=True)
        return False

def generate_slug(text, lang='en'):
    """Автоматично генерує SEO-оптимізований slug з тексту"""
    if not text:
        return None
    
    # Перетворюємо на нижній регістр і замінюємо пробіли дефісами
    text = text.lower().strip()
    
    # Транслітерація для різних мов
    if lang == 'sk':
        # Словацька транслітерація
        transliteration_map = {
            'á': 'a', 'ä': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'í': 'i', 
            'ĺ': 'l', 'ľ': 'l', 'ň': 'n', 'ó': 'o', 'ŕ': 'r', 'š': 's', 
            'ť': 't', 'ú': 'u', 'ý': 'y', 'ž': 'z'
        }
    elif lang == 'pl':
        # Польська транслітерація
        transliteration_map = {
            'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n', 
            'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z'
        }
    elif lang == 'hu':
        # Угорська транслітерація
        transliteration_map = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ö': 'o', 'ő': 'o',
            'ú': 'u', 'ü': 'u', 'ű': 'u'
        }
    else:  # en - англійська транслітерація за замовчуванням
        transliteration_map = {}
    
    # Застосовуємо транслітерацію
    for char, replacement in transliteration_map.items():
        text = text.replace(char, replacement)
    
    # Замінюємо всі неалфавітні та нецифрові символи на дефіси
    slug = re.sub(r'[^a-z0-9]+', '-', text)
    
    # Видаляємо дефіси на початку та в кінці
    slug = slug.strip('-')
    
    # Замінюємо подвійні дефіси на одинарні
    slug = re.sub(r'-+', '-', slug)
    
    return slug

# Пошук по блогу
@app.route('/blog/search', methods=['GET'])
def blog_search():
    try:
        query = request.args.get('q', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 9  # 3x3 сітка статей
        
        if not query:
            return redirect(url_for('blog_index'))
        
        # Визначення поточної мови
        lang = session.get('language', app.config['BABEL_DEFAULT_LOCALE'])
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Запит для пошуку статей з врахуванням мови
            search_query = """
                SELECT 
                    bp.id,
                    bp.slug,
                    bp.featured_image,
                    bp.published_at,
                    bp.views,
                    bpt.title,
                    bpt.excerpt,
                    ts_rank_cd(to_tsvector(%s, bpt.title || ' ' || COALESCE(bpt.content, '')), plainto_tsquery(%s, %s)) AS rank
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                WHERE bp.published = TRUE
                AND (
                    to_tsvector(%s, bpt.title || ' ' || COALESCE(bpt.content, '')) @@ plainto_tsquery(%s, %s)
                    OR bpt.title ILIKE %s
                    OR bpt.content ILIKE %s
                )
                ORDER BY rank DESC
                LIMIT %s OFFSET %s
            """
            
            # Пошук у всьому тексті статті
            like_pattern = f'%{query}%'
            
            # Виконуємо пошук
            cursor.execute(search_query, [
                lang, lang, query,  # для ts_rank_cd
                lang,               # для join
                lang, lang, query,  # для to_tsvector
                like_pattern, like_pattern,  # для ILIKE
                per_page, (page - 1) * per_page  # для пагінації
            ])
            
            posts = cursor.fetchall()
            
            # Підраховуємо загальну кількість результатів для пагінації
            count_query = """
                SELECT COUNT(*)
                FROM blog_posts bp
                JOIN blog_post_translations bpt ON bp.id = bpt.post_id AND bpt.language = %s
                WHERE bp.published = TRUE
                AND (
                    to_tsvector(%s, bpt.title || ' ' || COALESCE(bpt.content, '')) @@ plainto_tsquery(%s, %s)
                    OR bpt.title ILIKE %s
                    OR bpt.content ILIKE %s
                )
            """
            
            cursor.execute(count_query, [
                lang,
                lang, lang, query,
                like_pattern, like_pattern
            ])
            
            total_posts = cursor.fetchone()[0]
            total_pages = (total_posts + per_page - 1) // per_page
            
            return render_template(
                'public/blog/search_results.html',
                query=query,
                posts=posts,
                total_posts=total_posts,
                page=page,
                total_pages=total_pages,
                lang=lang
            )
            
    except Exception as e:
        logging.error(f"Error in blog_search: {e}", exc_info=True)
        flash(_("An error occurred during search"), "error")
        return redirect(url_for('blog_index'))


# Список публікацій блогу


@app.route('/<token>/admin/blog/posts/new', methods=['GET', 'POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_blog_new_post(token):
    """Create a new blog post"""
    if request.method == 'POST':
        try:
            slug = request.form.get('slug', '').strip()
            featured_image = request.form.get('featured_image', '')
            published = request.form.get('published') == 'on'
            
            # If no slug provided, generate from title_sk
            if not slug:
                title_sk = request.form.get('title_sk', '').strip()
                slug = generate_slug(title_sk, 'sk')
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Create post in main table
                cursor.execute("""
                    INSERT INTO blog_posts 
                    (slug, author_id, featured_image, published, published_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id
                """, (
                    slug, 
                    session.get('user_id'), 
                    featured_image, 
                    published,
                    datetime.now() if published else None
                ))
                
                post_id = cursor.fetchone()[0]
                
                # Create translations for all languages
                languages = ['sk', 'en', 'pl', 'hu']
                
                for lang in languages:
                    title = request.form.get(f'title_{lang}', '').strip()
                    excerpt = request.form.get(f'excerpt_{lang}', '').strip()
                    content = request.form.get(f'content_{lang}', '').strip()
                    meta_title = request.form.get(f'meta_title_{lang}', '').strip()
                    meta_description = request.form.get(f'meta_description_{lang}', '').strip()
                    
                    # Skip if no translation provided
                    if not title and not content:
                        continue
                        
                    cursor.execute("""
                        INSERT INTO blog_post_translations 
                        (post_id, language, title, excerpt, content, meta_title, meta_description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        post_id, 
                        lang, 
                        title, 
                        excerpt, 
                        content, 
                        meta_title or title, 
                        meta_description or excerpt
                    ))
                
                # Save category associations
                categories = request.form.getlist('categories')
                for category_id in categories:
                    cursor.execute("""
                        INSERT INTO blog_post_categories 
                        (post_id, category_id)
                        VALUES (%s, %s)
                    """, (post_id, category_id))
                
                # Save tag associations
                tags = request.form.get('tags', '').strip().split(',')
                for tag_name in tags:
                    tag_name = tag_name.strip()
                    if not tag_name:
                        continue
                        
                    # Find tag or create new
                    cursor.execute("SELECT id FROM blog_tags WHERE slug = %s", (generate_slug(tag_name),))
                    tag_row = cursor.fetchone()
                    
                    if tag_row:
                        tag_id = tag_row[0]
                    else:
                        cursor.execute("""
                            INSERT INTO blog_tags (slug) 
                            VALUES (%s) 
                            RETURNING id
                        """, (generate_slug(tag_name),))
                        tag_id = cursor.fetchone()[0]
                        
                        # Create tag translations
                        for lang in languages:
                            cursor.execute("""
                                INSERT INTO blog_tag_translations 
                                (tag_id, language, name)
                                VALUES (%s, %s, %s)
                            """, (tag_id, lang, tag_name))
                    
                    # Create association
                    cursor.execute("""
                        INSERT INTO blog_post_tags 
                        (post_id, tag_id)
                        VALUES (%s, %s)
                    """, (post_id, tag_id))
                
                conn.commit()
                flash("Blog post created successfully", "success")
                return redirect(url_for('admin_blog_posts', token=token))
                
        except Exception as e:
            logging.error(f"Error creating blog post: {e}", exc_info=True)
            flash(f"Error creating blog post: {str(e)}", "error")
            return redirect(url_for('admin_blog_posts', token=token))
    
    # GET request - display the form
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Get categories for selection
            cursor.execute("""
                SELECT bc.id, bct.name
                FROM blog_categories bc
                JOIN blog_category_translations bct ON bc.id = bct.category_id 
                WHERE bct.language = 'sk'
                ORDER BY bct.name
            """)
            categories = cursor.fetchall()
            
            # Create supported languages dict for template
            supported_languages = {
                'sk': 'Slovenčina',
                'en': 'English',
                'pl': 'Polski',
                'hu': 'Magyar'
            }
            
            return render_template(
                'admin/blog/post_form.html',
                token=token,
                post=None,
                categories=categories,
                supported_languages=supported_languages,
                mode='create'
            )
            
    except Exception as e:
        logging.error(f"Error in admin_blog_new_post: {e}", exc_info=True)
        flash("Error loading form", "error")
        return redirect(url_for('admin_blog_posts', token=token))


# Зміна статусу публікації (опублікувати/приховати)
@app.route('/<token>/admin/blog/posts/<int:post_id>/toggle-publish', methods=['POST'])
@requires_token_and_roles('admin', 'manager')
@add_noindex_header
def admin_toggle_blog_post(token, post_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Отримуємо поточний статус
            cursor.execute("SELECT published FROM blog_posts WHERE id = %s", (post_id,))
            current_status = cursor.fetchone()[0]
            
            # Змінюємо статус
            new_status = not current_status
            now = datetime.now()
            
            # Оновлюємо запис
            if new_status:
                # Якщо публікуємо, встановлюємо дату публікації
                cursor.execute("""
                    UPDATE blog_posts 
                    SET published = TRUE, published_at = %s, updated_at = %s 
                    WHERE id = %s
                """, (now, now, post_id))
                flash("Post published successfully", "success")
            else:
                # Якщо приховуємо, прибираємо published прапорець
                cursor.execute("""
                    UPDATE blog_posts 
                    SET published = FALSE, updated_at = %s 
                    WHERE id = %s
                """, (now, post_id))
                flash("Post unpublished", "success")
            
            conn.commit()
            return redirect(url_for('admin_blog_posts', token=token))
            
    except Exception as e:
        logging.error(f"Error toggling blog post publish status: {e}", exc_info=True)
        flash("Error updating post status", "error")
        return redirect(url_for('admin_blog_posts', token=token))




@app.route('/<token>/admin/test-ftp')
@requires_token_and_roles('admin')
@add_noindex_header
def test_ftp_admin(token):
    """Test FTP connection from admin panel"""
    try:
        # FTP налаштування
        FTP_HOST = os.environ.get('FTP_HOST')
        FTP_USER = os.environ.get('FTP_USER')
        FTP_PASS = os.environ.get('FTP_PASS')
        
        if not FTP_HOST or not FTP_USER or not FTP_PASS:
            flash("FTP credentials not configured", "error")
            return redirect(url_for('admin_dashboard', token=token))
        
        # Розділяємо хост і порт, якщо вони вказані разом
        if ':' in FTP_HOST:
            host_parts = FTP_HOST.split(':')
            ftp_host = host_parts[0]
            ftp_port = int(host_parts[1])
        else:
            ftp_host = FTP_HOST
            ftp_port = 21
        
        # Тестуємо підключення
        ftp = ftplib.FTP()
        ftp.connect(ftp_host, ftp_port, timeout=10)
        ftp.login(FTP_USER, FTP_PASS)
        
        # Отримуємо список файлів для перевірки
        ftp.cwd('sub/image/products/')
        files = ftp.nlst()[:5]  # Перші 5 файлів
        
        ftp.quit()
        
        flash(f"FTP connection successful! Found {len(files)} files in products directory", "success")
        
    except ftplib.error_perm as e:
        flash(f"FTP permission error: {e}", "error")
    except ftplib.error_temp as e:
        flash(f"FTP temporary error: {e}", "error")
    except Exception as e:
        flash(f"FTP connection failed: {e}", "error")
    
    return redirect(url_for('admin_dashboard', token=token))



@app.route('/<token>/admin/generate-image-sitemap', methods=['GET'])
@requires_token_and_roles('admin')
@add_noindex_header
def admin_generate_image_sitemap(token):
    try:
        if generate_sitemap_images_file():
            flash("Image sitemap generated successfully", "success")
        else:
            flash("Error generating image sitemap", "error")
            
        return redirect(url_for('admin_dashboard', token=token))
    except Exception as e:
        logging.error(f"Error in admin_generate_image_sitemap: {e}", exc_info=True)
        flash("Error generating image sitemap", "error")
        return redirect(url_for('admin_dashboard', token=token))


if __name__ == '__main__':
    # Для локальної розробки
    os.makedirs(SITEMAP_DIR, exist_ok=True)
    
    # Ініціалізуємо планувальник для локальної розробки
    initialize_scheduler()
    
    # Генеруємо sitemap якщо немає
    sitemap_index_path = os.path.join(SITEMAP_DIR, 'sitemap-index.xml')
    if not os.path.exists(sitemap_index_path):
        logging.info("Generating initial sitemap...")
        generate_sitemap_index_file()
    
    port = int(os.environ.get('PORT', 5000))
    print(f"Запуск сервера на порту {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)