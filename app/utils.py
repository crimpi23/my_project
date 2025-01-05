# app/utils.py
import os
import psycopg2
from psycopg2 import pool
import logging

# Налаштування пулу підключень
connection_pool = psycopg2.pool.SimpleConnectionPool(
    1,  # Мінімальна кількість підключень
    20,  # Максимальна кількість підключень
    os.getenv("DATABASE_URL"),
    sslmode='require'
)

def get_connection():
    """
    Отримання підключення з пулу підключень.
    """
    try:
        conn = connection_pool.getconn()
        if conn:
            logging.debug("Successfully received connection from connection pool")
            return conn
    except Exception as e:
        logging.error(f"Error occurred while getting connection: {e}")

def release_connection(conn):
    """
    Повернення підключення у пул підключень.
    """
    try:
        connection_pool.putconn(conn)
        logging.debug("Successfully returned connection to connection pool")
    except Exception as e:
        logging.error(f"Error occurred while returning connection: {e}")

def import_to_db(table, file_path):
    """
    Імпортує дані з CSV файлу у вказану таблицю бази даних.
    Аргументи:
    table -- назва таблиці у базі даних
    file_path -- шлях до CSV файлу
    Повертає None.
    """
    conn = get_connection()
    cursor = conn.cursor()
    # Логіка для імпорту даних
    conn.commit()
    cursor.close()
    release_connection(conn)
