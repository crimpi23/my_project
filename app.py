import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user

app = Flask(__name__)

# Налаштування
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key')

# Заміна для SQLAlchemy сумісності з PostgreSQL
db_url = os.getenv('DATABASE_URL', 'sqlite:///data.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

# Логін-менеджер
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# Модель користувача
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class PriceList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, nullable=False)
    price_list_id = db.Column(db.Integer, db.ForeignKey('price_list.id'), nullable=False)
    price_list = db.relationship('PriceList', backref=db.backref('products', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query')
    results = []

    if not query:
        return render_template('search.html', query=query, results=results, error="Please provide a search query.")

    try:
        # Пошук в базі даних
        results = Product.query.filter(Product.article.ilike(f'%{query}%')).all()

    except Exception as e:
        # Логування помилки
        app.logger.error(f"Error during search: {e}")
        return render_template('search.html', query=query, results=results, error="An error occurred during the search.")

    return render_template('search.html', query=query, results=results, error=None)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('home'))
    return render_template('admin/dashboard.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
    return render_template('admin/login.html')

@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
