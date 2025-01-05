import csv
import os
import psycopg2
import logging

logging.basicConfig(level=logging.DEBUG)

def import_to_db(table, file_path, delimiter=';', encoding='utf-8'):
    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')
        cursor = conn.cursor()

        with open(file_path, newline='', encoding=encoding) as csvfile:
            reader = csv.reader(csvfile, delimiter=delimiter)
            headers = next(reader)
            logging.debug(f"Headers from CSV: {headers}")
            query = f"INSERT INTO {table} ({', '.join(headers)}) VALUES ({', '.join(['%s'] * len(headers))})"
            logging.debug(f"SQL Query: {query}")

            for row in reader:
                row = [row[0], row[1].replace(',', '.') if len(row) > 1 else row[1]]
                cursor.execute(query, row)
                logging.debug(f"Inserted row: {row}")

        conn.commit()
    except psycopg2.DatabaseError as db_error:
        logging.error(f"Database error: {db_error}")
        if conn:
            conn.rollback()
        raise db_error
    except Exception as e:
        logging.error(f"General error occurred: {e}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
