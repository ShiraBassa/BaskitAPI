import firebase_admin
from firebase_admin import credentials, db
import os
import json
from dotenv import load_dotenv

load_dotenv(dotenv_path="data.env")

cred_api = credentials.Certificate(json.loads(os.environ["BASKIT_API_KEY"]))
app_api = firebase_admin.initialize_app(cred_api, {
    'databaseURL': 'https://baskitapi-default-rtdb.firebaseio.com/'
}, name="baskit_api_app")

cred_baskit = credentials.Certificate(json.loads(os.environ["BASKIT_KEY"]))
app_baskit = firebase_admin.initialize_app(cred_baskit, {
    'databaseURL': 'https://baskit-b6600-default-rtdb.firebaseio.com/'
}, name="baskit_app")
    
stores_items_ref = db.reference('Stores-Items', app=app_api)
items_stores_ref = db.reference('Items-Stores', app=app_api)
stores_urls_ref = db.reference('Stores-Urls', app=app_api)
items_info_ref = db.reference('Items_Info', app=app_api)
users_choices_ref = db.reference('Users-Choices', app=app_api)
stores_branches_ref = db.reference('Stores-Branches', app=app_api)
items_categories_ref = db.reference('Items-Categories', app=app_api)
groups_ref = db.reference('Groups', app=app_api)