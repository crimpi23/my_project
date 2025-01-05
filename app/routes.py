from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from .forms import ArticleForm, UploadForm
from .utils import get_connection, import_to_db
import logging

bp = Blueprint('main', __name__)

logging.basicConfig(level=logging.DEBUG)

@bp.route("/<token>/", methods=["GET", "POST"])
def index(token):
    form = ArticleForm()
    if form.validate_on_submit():
        # Логіка для обробки форми
        pass
    return render_template('index.html', form=form, token=token)

@bp.route("/<token>/add_to_cart", methods=["POST"])
def add_to_cart(token):
    # Логіка для додавання до кошика
    pass

@bp.route("/<token>/cart", methods=["GET"])
def view_cart(token):
    # Логіка для перегляду кошика
    pass

@bp.route("/<token>/upload", methods=["GET", "POST"])
def upload(token):
    form = UploadForm()
    if form.validate_on_submit():
        # Логіка для завантаження файлу
        pass
    return render_template('upload.html', form=form, token=token)
