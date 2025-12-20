import sys
import os
from functools import wraps
from flask import Flask, request, jsonify, Response
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
import click
from flask.cli import show_server_banner
from time import sleep
from firebase_admin import auth
from functools import wraps
import ast
from flask_compress import Compress

# Disable Flask server banner
click.echo = lambda *args, **kwargs: None
show_server_banner = lambda *args, **kwargs: None
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Classes.userHandler import User
from Classes.msgBarHandler import msg_bar
from Data.data_sets import app_baskit

app = Flask(__name__)
Compress(app)
users = {}
user_selections = {}

# JWT decorator to protect endpoints
def firebase_token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        firebase_token = request.headers.get("FirebaseToken", "")

        if not firebase_token:
            return jsonify({"error": "Token missing or invalid"}), 401

        try:
            decoded_token = auth.verify_id_token(firebase_token, app=app_baskit)
            user_id = decoded_token['uid']

        except Exception as e:
            return jsonify({"error": "Invalid token", "details": str(e)}), 401
        
        return f(user_id, *args, **kwargs)
    
    return decorated

# Login: returns JWT token
@app.route("/user", methods=["POST"])
@firebase_token_required
def user_certification(user_id):
    if not user_id in users.keys():
        users[user_id] = User(user_id)
        print(user_id)

    return jsonify({"message": f"User {user_id} registered"}), 200

# Cities endpoint
@app.route("/cities", methods=["GET", "POST"])
@firebase_token_required
def cities_function(user_id):
    if request.method == "POST":
        data = request.get_json()  # parse JSON automatically

        if not data or "cities" not in data:
            return jsonify({"message": "No cities provided"}), 400

        cities = data["cities"]
        users[user_id].set_cities(cities)

        return jsonify({"message": "Cities set"}), 200
    
    elif request.method == "GET":
        cities = users[user_id].cities
        return jsonify(cities)  # <- always return JSON array
    
@app.route("/all_cities", methods=["GET"])
@firebase_token_required
def all_cities_function(user_id):
    if request.method == "GET":
        cities = users[user_id].get_all_cities()
        return jsonify(cities)  # <- always return JSON array
    

# Stores endpoint
@app.route("/stores", methods=["GET", "POST"])
@firebase_token_required
def stores_function(user_id):
    if request.method == "POST":
        data = request.get_json()  # parse JSON automatically

        if not data or "stores" not in data:
            return jsonify({"message": "No stores provided"}), 400

        stores = data["stores"]  # now a proper list
        users[user_id].set_stores(stores)

        return jsonify({"message": "Stores set"}), 200

    elif request.method == "GET":
        stores = users[user_id].get_all_stores()
        return jsonify(stores)  # <- always return JSON array
    
# Branches endpoint
@app.route("/branches", methods=["GET", "POST"])
@firebase_token_required
def branches_function(user_id):
    if request.method == "POST":
        data = request.get_json()
    
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON"}), 400
    
        stores_branches = data
        msg_bar_handler = msg_bar(len(stores_branches))
        
        users[user_id].set_branches(stores_branches, msg_bar_handler)

        msg_bar_handler.close()
        
        return jsonify({"message": "Branches set"}), 200
    
    elif request.method == "GET":
        branches_dict = users[user_id].get_all_branches()
        return jsonify(branches_dict)  # <- always return JSON object

@app.route("/choices", methods=["GET"])
@firebase_token_required
def get_choices(user_id):
    if request.method == "GET":
        branches_dict = users[user_id].get_choices()
        return jsonify(branches_dict)  # <- always return JSON object

@app.route("/items", methods=["GET"])
@firebase_token_required
def get_item_names(user_id):
    items = users[user_id].get_all_items()
    
    if items:
        return items
    
    return jsonify({"message": "No items"}), 404

@app.route("/item_name", methods=["GET"])
@firebase_token_required
def get_item_name(user_id):
    item_code = request.args.get("item_code")
    
    if not item_code:
        return jsonify({"message": "item_code not provided"}), 400

    item_name = users[user_id].get_item_name(item_code)
    
    if item_name:
        return item_name
    
    return jsonify({"message": "No name for this item"}), 404

@app.route("/items_code_name", methods=["POST"])
@firebase_token_required
def get_items_code_name(user_id):
    data = request.get_json()

    if not data or "item_codes" not in data:
        return jsonify({"message": "item_codes not provided"}), 400

    item_codes = data["item_codes"]
    items_code_name = users[user_id].get_items_code_name(item_codes)
    
    return items_code_name

@app.route("/item_code", methods=["GET"])
@firebase_token_required
def get_item_code(user_id):
    item_name = request.args.get("item_name")
    
    if not item_name:
        return jsonify({"message": "item_name not provided"}), 400

    item_code = users[user_id].get_item_code(item_name)
    
    if item_code:
        return item_code
    
    return jsonify({"message": "No name for this item"}), 404

@app.route("/item_prices", methods=["GET"])
@firebase_token_required
def get_item_prices(user_id):
    item_name = request.args.get("item_name")
    item_code = request.args.get("item_code")

    if item_code:
        item_prices = users[user_id].get_item_prices_by_code(item_code)
    elif item_name:
        item_prices = users[user_id].get_item_prices_by_name(item_name)
    else:
        return jsonify({"message": "item_code/item_name not provided"}), 400
    
    if item_prices:
        return item_prices
    
    return jsonify({"message": "No prices found for this item"}), 404

@app.get("/active")
def isActive():
    return {"ok": True}, 200

# Default route
@app.route("/")
def default_route():
    return jsonify({"message": 
        "Please choose one of these options: ..."}), 200

if __name__ == "__main__":
    print("\033c")
    app.run(host="0.0.0.0", port=5001, debug=True)