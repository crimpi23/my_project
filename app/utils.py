# app/utils.py

import logging
import psycopg2
from psycopg2 import pool
from flask import current_app as app

# Ваша поточна реалізація get_connection, release_connection, import_to_db
def get_connection():
    return app.config['POOL'].getconn()

def release_connection(conn):
    app.config['POOL'].putconn(conn)

def import_to_db(table, file):
    # Ваша реалізація імпорту до БД
    pass

# Додаємо нові функції
def get_existing_tables():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = cursor.fetchall()
        return [table[0] for table in tables]
    except Exception as e:
        logging.error(f"Error occurred while fetching tables: {e}")
        return []
    finally:
        cursor.close()
        release_connection(conn)

def get_cart_items(token):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        if not user:
            return []
        
        user_id = user[0]
        cursor.execute("""
            SELECT p.article, p.table_name, p.price, c.quantity, c.added_at, p.id
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()
        return cart_items
    except Exception as e:
        logging.error(f"Error occurred while fetching cart items: {e}")
        return []
    finally:
        cursor.close()
        release_connection(conn)

def calculate_total_price(cart_items):
    total_price = sum(item[2] * item[3] for item in cart_items)  # Ціна помножена на кількість
    return total_price
