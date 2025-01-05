import os
import psycopg2
import logging
import tempfile

def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logging.error("DATABASE_URL is not set")
        raise Exception("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode='require')

def import_to_db(table, file_path):
    conn = get_connection()
    cursor = conn.cursor()
    # Логіка для імпорту даних
    conn.commit()
    cursor.close()
    conn.close()
