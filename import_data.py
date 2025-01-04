import csv
import os
import psycopg2
import logging

# Налаштування логування
logging.basicConfig(level=logging.DEBUG)

def import_to_db(table, file_path):
    # Підключення до бази даних
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')
    cursor = conn.cursor()

    try:
        # Відкриваємо файл CSV, вказуємо роздільник - крапка з комою
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')  # Вказуємо правильний роздільник

            # Зчитуємо заголовки стовпців
            headers = next(reader)
            logging.debug(f"Headers from CSV: {headers}")  # Логування заголовків

            # Генерація SQL запиту для вставки даних
            query = f"INSERT INTO {table} ({', '.join(headers)}) VALUES ({', '.join(['%s'] * len(headers))})"
            logging.debug(f"SQL Query: {query}")  # Логування SQL запиту

            # Вставляємо кожен рядок
            for row in reader:
                # Перетворюємо ціну з коми на точку
                row = [row[0], row[1].replace(',', '.') if len(row) > 1 else row[1]]  # Артикул і ціна
                cursor.execute(query, row)
                logging.debug(f"Inserted row: {row}")  # Логування кожного вставленого рядка

        conn.commit()
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()
