import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/db_name")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
