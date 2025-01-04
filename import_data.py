import csv
import psycopg2

def import_to_db(table, file_path):
    # Підключення до бази даних
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')
    cursor = conn.cursor()

    with open(file_path, newline='') as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader)  # Перша строка - це заголовки стовпців
        
        # Генерація SQL запиту для вставки даних
        query = f"INSERT INTO {table} ({', '.join(headers)}) VALUES ({', '.join(['%s'] * len(headers))})"
        
        # Вставляємо кожен рядок
        for row in reader:
            cursor.execute(query, row)

    conn.commit()
    cursor.close()
    conn.close()
