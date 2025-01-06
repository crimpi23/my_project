from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from app import get_connection, is_admin

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Управління користувачами
@admin_bp.route("/users", methods=["GET", "POST"])
def manage_users():
    if not is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        username = request.form.get("username")
        password = generate_password_hash(request.form.get("password"))
        token = request.form.get("token")
        cursor.execute(
            "INSERT INTO users (username, password, token) VALUES (%s, %s, %s)",
            (username, password, token),
        )
        conn.commit()

    cursor.execute("SELECT id, username, token FROM users")
    users = cursor.fetchall()
    conn.close()

    return render_template("admin/users.html", users=users)

# Управління прайсами
@admin_bp.route("/prices", methods=["GET", "POST"])
def manage_prices():
    if not is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        table_name = request.form.get("table_name")
        cursor.execute("CREATE TABLE IF NOT EXISTS %s (id SERIAL PRIMARY KEY, article TEXT, price NUMERIC)", (table_name,))
        conn.commit()

    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    tables = cursor.fetchall()
    conn.close()

    return render_template("admin/prices.html", tables=tables)

# Управління замовленнями
@admin_bp.route("/orders", methods=["GET"])
def manage_orders():
    if not is_admin():
        return redirect(url_for("admin.admin_login"))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT o.id, u.username, p.article, p.price, o.quantity, o.created_at
        FROM orders o
        JOIN users u ON o.user_id = u.id
        JOIN products p ON o.product_id = p.id
    """)
    orders = cursor.fetchall()
    conn.close()

    return render_template("admin/orders.html", orders=orders)
