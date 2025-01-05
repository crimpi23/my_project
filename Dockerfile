# Використовуємо легковаговий образ Python
FROM python:3.9-slim

# Встановлення робочої директорії
WORKDIR /app

# Копіюємо файл з вимогами та встановлюємо залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду додатку
COPY . .

# Встановлюємо порт додатку
EXPOSE 5000

# Команда для запуску додатку
CMD ["python", "app.py"]

# Додавання підтримки змінних середовища
ENV FLASK_APP=app.py
ENV FLASK_ENV=development

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl --fail http://localhost:5000/ || exit 1
