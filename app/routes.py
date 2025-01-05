# app/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from .forms import ArticleForm, UploadForm
from .utils import get_connection, release_connection, import_to_db
import logging

bp = Blueprint('main', __name__)

logging.basicConfig(level=logging.DEBUG)

@bp.route("/<token>/", methods=["GET", "POST"])
def index(token):
    form = ArticleForm()
    if form.validate_on_submit():
        article = form.article.data
        articles = form.articles.data
        # Логіка для обробки форми
        conn = get_connection()
        cursor = conn.cursor()
        # Запити до бази даних
        cursor.close()
        release_connection(conn)
    return render_template('index.html', form=form, token=token)

# Інші маршрути залишаються без змін
