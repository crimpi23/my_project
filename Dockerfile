# Використовуємо легковаговий образ Python
FROM python:3.9-slim

# Встановлення робочої директорії
WORKDIR /app

# Копіюємо requirements.txt і встановлюємо залежності
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Відкриваємо порт для додатку
EXPOSE 5000

# Команда для запуску додатку
CMD ["python", "app.py"]
