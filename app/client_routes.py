
from flask import Blueprint, jsonify

client = Blueprint("client", __name__)

@client.route("/cart")
def cart():
    return jsonify({"message": "User Cart"}), 200
