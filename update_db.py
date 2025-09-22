import firebase_admin
from firebase_admin import credentials, db
import requests
import gzip
import xml.etree.ElementTree as ET
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from threading import Lock
from concurrent.futures import as_completed
import traceback

cred = credentials.Certificate("baskitapi-firebase-adminsdk-fbsvc-52318252b7.json")

# Only initialize if no app exists
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://baskitapi-default-rtdb.firebaseio.com/'
    })

stores_items_ref = db.reference('Stores-Items')
items_stores_ref = db.reference('Items-Stores')
stores_urls_ref = db.reference('Stores-Urls')

def update_all_stores(hanlders={}):
    stores = stores_urls_ref.get()

    if not stores:
        return
    
    for store in stores:
        update_store(store, hanlders[store] or None)
        
def update_store(store_name, hanlder):
    branch_urls = list(stores_urls_ref.child(store_name).get().items())
    global_bar_lock = Lock()
    
    with tqdm(total=len(branch_urls), desc="All Branches", position=0) as global_bar:
        with ThreadPoolExecutor() as executor:
            futures = []
            for branch_name, branch_url in branch_urls:
                futures.append(executor.submit(update_branch, store_name, branch_name, branch_url, hanlder))
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Branch update generated an exception: {exc}")
                    traceback.print_exc()  # full stack trace
                with global_bar_lock:
                    global_bar.update(1)

def update_branch(store_name, branch_name, branch_url, store_handler=None):
    gz_file_path = None
    xml_file_path = None

    # Download the gzipped XML file
    response = requests.get(branch_url, stream=True)

    if response.status_code != 200 and store_handler:
        new_url = store_handler.update_url(branch_name)
        stores_urls_ref.child(store_name).child(branch_name).set(new_url)
        response = requests.get(new_url, stream=True)
        branch_url = new_url

    # Create a temporary file to save the gzipped content
    with tempfile.NamedTemporaryFile(delete=False) as tmp_gz_file:
        for chunk in response.iter_content(chunk_size=8192):
            tmp_gz_file.write(chunk)
        gz_file_path = tmp_gz_file.name

    # Decompress the gzipped file to another temporary file
    with gzip.open(gz_file_path, 'rb') as f_in:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_xml_file:
            tmp_xml_file.write(f_in.read())
            xml_file_path = tmp_xml_file.name

    # Parse the XML file
    tree = ET.parse(xml_file_path)
    root = tree.getroot()

    branch_updates = {}
    item_updates = {}
    old_items = items_stores_ref.get() or {}
    old_branch = stores_items_ref.child(store_name).child(branch_name).get() or {}
    
    # Assuming the XML structure has items as children of root
    # and each item has fields like 'ManufacturerItemDescription', 'ItemPrice', etc.
    items = list(root.findall('./Items/Item'))
    desc = f"{store_name} items"
    
    with tqdm(total=len(items) if items else None, desc=desc, position=1, leave=False) as store_bar:
        for item in items:
            # Extract fields with proper decoding
            item_name = item.find('ItemCode').text.strip()
            price = float(item.find('ItemPrice').text.strip())

            if item_name is None or price is None:
                store_bar.update(1)
                continue

            if item_name in old_branch:
                if old_branch[item_name] != price: # Don't put continue here!!!!! it will skip the other tree
                    branch_updates[item_name] = price
            else:
                branch_updates[item_name] = price

            if item_name in old_items:
                # Copy the existing structure deeply enough to not lose branches
                item_updates[item_name] = dict(old_items[item_name])

                if store_name in item_updates[item_name]:
                    if branch_name in item_updates[item_name][store_name] and \
                        item_updates[item_name][store_name][branch_name] == price:
                        continue
                else:
                    item_updates[item_name][store_name] = {}
                
                # Ensure branch dict is preserved
                item_updates[item_name][store_name] = dict(item_updates[item_name][store_name])
                item_updates[item_name][store_name][branch_name] = price

            else:
                # New item entirely
                item_updates[item_name] = {
                    store_name: {
                        branch_name: price
                    }
                }
            store_bar.update(1)

    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if item_updates:
        items_stores_ref.update(item_updates)
    
    # Remove temporary files safely
    try:
        if gz_file_path and os.path.exists(gz_file_path):
            os.remove(gz_file_path)
        if xml_file_path and os.path.exists(xml_file_path):
            os.remove(xml_file_path)
    except Exception as e:
        print(f"Error removing temporary files: {e}")


def add_branch(store_name, branch_name, branch_url, store_handler):
    stores_urls_ref.child(store_name).child(branch_name).set(branch_url)
    update_branch(store_name, branch_name, branch_url, store_handler)

def if_branch_exists(store_name, branch_name):
    return stores_urls_ref.child(store_name).child(branch_name).get() is not None