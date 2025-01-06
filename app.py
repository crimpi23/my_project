import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.from_object("config.Config")
csrf = CSRFProtect(app)

# Підключення до бази даних
def get_connection():
    return psycopg2.connect(app.config["DATABASE_URL"], sslmode="require")

# Перевірка авторизації адміністратора
def is_admin():
    return session.get("is_admin", False)

# Головна сторінка адміністратора
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM admins WHERE username = %s", (username,))
        admin = cursor.fetchone()
        conn.close()

        if admin and check_password_hash(admin[0], password):
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template("admin/login.html", error="Невірні дані")

    return render_template("admin/login.html")

@app.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("admin_login"))
    return render_template("admin/dashboard.html")

# Вихід адміністратора
@app.route("/admin/logout", methods=["GET"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))
@app.route("/admin/prices", methods=["GET", "POST"])
def manage_prices():
    if not is_admin():
        return redirect(url_for("admin_login"))

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        table_name = request.form.get("table_name")
        cursor.execute("INSERT INTO price_lists (table_name) VALUES (%s)", (table_name,))
        conn.commit()

    cursor.execute("SELECT table_name FROM price_lists")
    tables = cursor.fetchall()
    conn.close()

    return render_template("admin/prices.html", tables=tables)
@app.route("/admin/users", methods=["GET", "POST"])
def manage_users():
    if not is_admin():
        return redirect(url_for("admin_login"))

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        username = request.form.get("username")
        token = uuid.uuid4().hex
        cursor.execute("INSERT INTO users (token, is_admin) VALUES (%s, FALSE)", (token,))
        conn.commit()

    cursor.execute("SELECT token, created_at FROM users")
    users = cursor.fetchall()
    conn.close()

    return render_template("admin/users.html", users=users)
@app.route("/admin/orders", methods=["GET"])
def manage_orders():
    if not is_admin():
        return redirect(url_for("admin_login"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, u.token, p.article, p.table_name, p.price, c.quantity, c.added_at
        FROM cart c
        JOIN users u ON c.user_id = u.id
        JOIN products p ON c.product_id = p.id
    """)
    orders = cursor.fetchall()
    conn.close()

    return render_template("admin/orders.html", orders=orders)
