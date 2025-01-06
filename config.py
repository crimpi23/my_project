import os

# Завантажуємо URL бази даних із змінних середовища
DATABASE_URL = os.getenv('DATABASE_URL')

# Замінюємо `postgres://` на `postgresql://` для сумісності з SQLAlchemy
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Налаштування SQLAlchemy
SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False
