import sys
import os
from functools import wraps
from flask import Flask, request, jsonify, Response
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
import click
from firebase_admin import auth
from flask_compress import Compress
from typing import Any, Dict
import uuid
from threading import Lock
import time

click.echo = lambda *args, **kwargs: None
show_server_banner = lambda *args, **kwargs: None
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Classes.userHandler import User
from Data.data_sets import (
    app_baskit,
    STORE_CONFIG,
    stores_branches_ref,
    items_info_ref,
    items_categories_ref
)
from RequestClasses.generalRequestsFns import get_branches

app = Flask(__name__)
Compress(app)
users = {}
users_lock = Lock()
user_selections = {}

CACHE_TTL = 10
cache = {}

def build_categories_from_item_infos():
    items_info = items_info_ref.get() or {}

    categories = {}

    for item_code, item_info in items_info.items():
        if not isinstance(item_info, dict):
            continue

        category = item_info.get("category")

        if not category:
            continue

        categories[item_code] = category

    return categories


def get_category_by_code(item_code: str):
    item_info = items_info_ref.child(item_code).get() or {}

    if isinstance(item_info, dict):
        category = item_info.get("category")

        if category:
            return category

    return items_categories_ref.child(item_code).get()

def ensure_user(user_id: str) -> User:
    with users_lock:
        if user_id not in users:
            users[user_id] = User(user_id)

        return users[user_id]


def ok(data: Any = None, status: int = 200):
    if data is None:
        return jsonify({"ok": True}), status
    
    if isinstance(data, Response):
        return data, status
    
    return jsonify(data), status


def err(message: str, status: int = 400, **details):
    payload: Dict[str, Any] = {"ok": False, "error": message}
    
    if details:
        payload["details"] = details
    
    return jsonify(payload), status


def safe_json():
    return request.get_json(silent=True)

def get_cache(key):
    entry = cache.get(key)

    if not entry:
        return None
    
    data, ts = entry
    
    if time.time() - ts > CACHE_TTL:
        cache.pop(key, None)
        return None
    
    return data

def set_cache(key, value):
    cache[key] = (value, time.time())

def firebase_token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        firebase_token = request.headers.get("FirebaseToken", "")

        if not firebase_token:
            return err("Token missing", status=401)

        try:
            decoded_token = auth.verify_id_token(firebase_token, app=app_baskit)
            user_id = decoded_token.get("uid")
            
            if not user_id:
                return err("Invalid token", status=401)
        
        except Exception:
            return err("Invalid token", status=401)

        ensure_user(user_id)
        return f(user_id, *args, **kwargs)

    return decorated


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    request_id = str(uuid.uuid4())[:8]
    app.logger.exception(f"[{request_id}] Unhandled exception: {e}")
    return err("Internal server error", status=500, request_id=request_id)


@app.route("/user", methods=["POST"])
@firebase_token_required
def user_certification(user_id):
    ensure_user(user_id)
    print("- User " + user_id + " signed")
    return ok({"message": f"User {user_id} registered"}, status=200)


@app.route("/cities", methods=["GET", "POST"])
@firebase_token_required
def cities_function(user_id):
    if request.method == "POST":
        data = safe_json()
        
        if not isinstance(data, dict) or "cities" not in data:
            return err("No cities provided", status=400)

        cities = data["cities"]
        ensure_user(user_id).set_cities(cities)
        print("- User " + user_id + " set cities")

        return ok({"message": "Cities set"}, status=200)

    elif request.method == "GET":
        cities = ensure_user(user_id).cities
        return ok(cities, status=200)


@app.route("/all_cities", methods=["GET"])
@firebase_token_required
def all_cities_function(user_id):
    cities = ensure_user(user_id).get_all_cities()
    return ok(cities, status=200)


# Stores endpoint
@app.route("/stores", methods=["GET"])
@firebase_token_required
def stores_function(user_id):
    if request.method == "GET":
        stores = ensure_user(user_id).get_all_stores()
        return ok(stores, status=200)


# Branches endpoint
@app.route("/branches", methods=["POST"])
@firebase_token_required
def branches_function(user_id):
    data = safe_json()
    
    if not isinstance(data, dict):
        return err("Invalid JSON", status=400)

    ensure_user(user_id).set_branches(data)
    print("- User " + user_id + " set branches")

    return ok({"message": "Branches set"}, status=200)


@app.route("/choices", methods=["GET"])
@firebase_token_required
def get_choices(user_id):
    if request.method == "GET":
        try:
            branches_dict = ensure_user(user_id).get_choices()
            return ok(branches_dict or {}, status=200)
        
        except Exception as e:
            app.logger.exception(f"choices failed: {e}")
            return ok({}, status=200)


@app.route("/items_prices", methods=["GET"])
@firebase_token_required
def get_item_names(user_id):
    user = ensure_user(user_id)

    if not user.choices:
        return ok({}, status=200)

    cache_key = f"items_prices:{user_id}"
    cached = get_cache(cache_key)

    if cached is not None:
        return ok(cached, status=200)

    try:
        items = user.get_all_items()
        items = items or {}
        set_cache(cache_key, items)

        return ok(items, status=200)
    
    except Exception as e:
        app.logger.exception(f"items_prices failed: {e}")
        return ok({}, status=200)

@app.route("/groups", methods=["GET"])
@firebase_token_required
def get_groups(user_id):
    user = ensure_user(user_id)

    if not user.choices:
        return ok({}, status=200)

    cache_key = f"groups:{user_id}"
    cached = get_cache(cache_key)

    if cached is not None:
        return ok(cached, status=200)

    try:
        groups = user.get_groups()
        groups = groups or {}
        set_cache(cache_key, groups)

        return ok(groups, status=200)
    
    except Exception as e:
        app.logger.exception(f"groups failed: {e}")
        return ok({}, status=200)

@app.route("/item_infos", methods=["GET"])
@firebase_token_required
def get_items_info(user_id):
    user = ensure_user(user_id)
    
    if not user.choices:
        return ok({}, status=200)

    cache_key = f"item_infos:{user_id}"
    cached = get_cache(cache_key)

    if cached is not None:
        return ok(cached, status=200)

    try:
        item_infos = user.get_item_infos()
        item_infos = item_infos or {}
        set_cache(cache_key, item_infos)

        return ok(item_infos, status=200)
    
    except Exception as e:
        app.logger.exception(f"item_infos failed: {e}")
        return ok({}, status=200)

@app.route("/item_prices", methods=["GET"])
@firebase_token_required
def get_item_prices(user_id):
    item_code = request.args.get("item_code")

    if item_code:
        item_prices = ensure_user(user_id).get_item_prices_by_code(item_code)
    else:
        return err("item_code not provided", status=400)

    if item_prices:
        return ok(item_prices, status=200)

    return ok({}, status=200)

@app.route("/preview_items", methods=["GET"])
@firebase_token_required
def preview_items(user_id):
    store = request.args.get("store")
    branch = request.args.get("branch")

    if not store or not branch:
        return err("store and branch required", status=400)

    user = ensure_user(user_id)

    # Temporary single-branch fetch
    temp_user = User(is_admin=True)
    temp_user.set_branches({store: [branch]})

    items = temp_user.get_all_items()

    if items:
        return ok(items, status=200)

    return err("No items found", status=404)

@app.route("/all_branches", methods=["GET"])
@firebase_token_required
def all_branches_bulk(user_id):
    user = ensure_user(user_id)
    all_branches = stores_branches_ref.get()

    if not all_branches:
        return err("No avalible stores yet", status=404)
    
    all_branches = dict(all_branches)
    all_branches_chosen = {}

    cities = request.args.getlist("cities")

    if not cities:
        cities = user.cities

    for store in all_branches:
        branches = get_branches(all_branches[store], cities)
        if branches: all_branches_chosen[store] = branches

    return ok(all_branches_chosen, status=200)

@app.route("/categories", methods=["GET"])
@firebase_token_required
def get_categories(user_id):
    cache_key = "categories:global"
    cached = get_cache(cache_key)

    if cached is not None:
        return ok(cached, status=200)

    categories = build_categories_from_item_infos()

    if not categories:
        categories = items_categories_ref.get() or {}

    set_cache(cache_key, categories)

    return ok(categories, status=200)

@app.route("/item_category", methods=["GET"])
@firebase_token_required
def get_item_category(user_id):
    code = request.args.get("item_code")
    name = request.args.get("item_name")

    if not code and not name:
        return err("item code/name required", status=400)

    user = ensure_user(user_id)

    if code:
        category = get_category_by_code(code) or "חסר"
    else:
        category = user.get_item_category_by_name(name) or "חסר"

    return ok({"category": category}, status=200)

@app.get("/health")
def isActive():
    return ok({"ok": True}, status=200)


# Default route
@app.route("/")
def default_route():
    return ok({"message": "Please spacify a valid endpoint"}, status=200)


if __name__ == "__main__":
    print("\033c")
    app.run(host="0.0.0.0", port=10000, debug=False, threaded=True)