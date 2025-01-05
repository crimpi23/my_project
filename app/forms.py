# app/forms.py
"""
Цей файл містить всі форми для додатку.
"""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, FileField, SubmitField
from wtforms.validators import DataRequired, Length

class ArticleForm(FlaskForm):
    """
    Форма для введення артикула та списку артикулів.
    """
    article = StringField('Article', validators=[DataRequired(), Length(min=1, max=100)])
    articles = TextAreaField('Articles', validators=[Length(max=1000)])
    submit = SubmitField('Submit')

class UploadForm(FlaskForm):
    """
    Форма для завантаження прайс-листа.
    """
    table = StringField('Table', validators=[DataRequired()])
    file = FileField('File', validators=[DataRequired()])
    submit = SubmitField('Upload')
