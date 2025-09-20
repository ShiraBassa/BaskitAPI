from flask import Flask, request, jsonify, render_template_string
from data_sets import getCities
from supermarketsHandler import get_store_names
import json
from urllib.parse import unquote_plus
from flask import render_template_string
import firebase_admin
from firebase_admin import credentials, db
from update_db import add_store, if_store_exists

cred = credentials.Certificate("baskitapi-firebase-adminsdk-fbsvc-52318252b7.json")

# Only initialize if no app exists
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://baskitapi-default-rtdb.firebaseio.com/'
    })


# Access Stores
stores_items_ref = db.reference('Stores-Items')

# Access Items
items_stores_ref = db.reference('Items-Stores')

app = Flask(__name__)

user_selections = {}
user_urls = {}

@app.route("/cities", methods=["GET"])
def get_cities():
    abbr = request.args.get("abbr", False)

    return app.response_class(
        response=json.dumps(getCities(abbr), ensure_ascii=False),
        status=200,
        mimetype='application/json; charset=utf-8'
    )

@app.route("/stores", methods=["GET"])
def get_stores():
    user_id = request.args.get("userId")
    cities = request.args.getlist("cities")

    if not cities:
        return jsonify({"error": "cities required"}), 400
    
    response, user_urls[user_id] = get_store_names(cities)

    return app.response_class(
        response=json.dumps(response, ensure_ascii=False),
        status=200,
        mimetype='application/json; charset=utf-8'
    )

@app.route("/user-selection", methods=["POST"])
def user_selection():
    data = request.get_json()
    user_id = data.get("userId")
    stores = data.get("stores", [])

    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    user_selections[user_id] = [unquote_plus(store).replace("\\", '"') for store in stores]

    for selection in user_selections[user_id]:
        if not if_store_exists(selection):
            add_store(selection, user_urls[user_id][selection]["url"])

    return jsonify({"status": "ok"}), 200

@app.route("/")
def main():
    if request.accept_mimetypes['application/json'] >= request.accept_mimetypes['text/html']:
        return "Please choose one of these options:\n" + \
            "- Get Cities - /cities\n" + \
            "- Get Stores - /stores?cities\n" + \
            "- User Selection - /user-selection\n"
    
    else:
        html = """
        <html>
          <head><title>Baskit API</title></head>
          <body>
            <h1>Please choose one of these options:</h1>
            <ul>
              <li>Get Cities - /cities</li>
              <li>Get Stores - /stores?cities</li>
              <li>User Selection - /user-selection</li>
            </ul>
          </body>
        </html>
        """
        return render_template_string(html)
    
if __name__ == "__main__":
    app.run(debug=True)