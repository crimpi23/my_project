
from flask import Blueprint, jsonify

admin = Blueprint("admin", __name__)

@admin.route("/dashboard")
def dashboard():
    return jsonify({"message": "Admin Dashboard"}), 200
