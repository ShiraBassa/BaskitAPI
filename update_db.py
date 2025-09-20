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
from requestsOne import RequestsClassOne

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

# Access Items
stores_urls_ref = db.reference('Stores-Urls')

def update_store(store_name, store_url, store_total_items=None):
    gz_file_path = None
    xml_file_path = None
    try:
        # Download the gzipped XML file
        response = requests.get(store_url, stream=True)

        if response.status_code == 403:
            store_url = RequestsClassOne.get_updated_url(store_name, store_url.split("https://pricesprodpublic.blob.core.windows.net/")[1]
                                        .split("/")[0])
            stores_urls_ref.child(store_name).set(store_url)
            response = requests.get(store_url, stream=True)

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

        store_updates = {}
        item_updates = {}
        old_items = items_stores_ref.get()
        old_store = stores_items_ref.get(store_name)

        # Assuming the XML structure has items as children of root
        # and each item has fields like 'ManufacturerItemDescription', 'ItemPrice', etc.
        items = list(root.findall('./Items/Item'))
        desc = f"{store_name} items"
        with tqdm(total=len(items) if items else None, desc=desc, position=1, leave=False) as store_bar:
            for item in items:
                # Extract fields with proper decoding
                try:
                    item_name = item.find('ItemCode').text.strip()
                    price = float(item.find('ItemPrice').text.strip())

                    if item_name is None or price is None:
                        store_bar.update(1)
                        continue
                except:
                    store_bar.update(1)
                    continue

                if item_name in old_store:
                    if old_store[item_name] != price:
                        store_updates[item_name] = price
                else:
                    store_updates[item_name] = price

                if item_name in old_items:
                    if store_name in old_items[item_name]:
                        if old_items[item_name][store_name] != price:
                            item_updates[item_name] = old_items[item_name]
                            item_updates[item_name][store_name] = price
                    else:
                        item_updates[item_name] = old_items[item_name]
                        item_updates[item_name][store_name] = price
                else:
                    item_updates[item_name] = {}
                    item_updates[item_name][store_name] = price

                store_bar.update(1)

        if store_updates:
            stores_items_ref.child(store_name).update(store_updates)

        if item_updates:
            items_stores_ref.update(item_updates)

    except Exception as e:
        print(e)

    finally:
    # Remove temporary files safely
        try:
            if gz_file_path and os.path.exists(gz_file_path):
                os.remove(gz_file_path)
            if xml_file_path and os.path.exists(xml_file_path):
                os.remove(xml_file_path)
        except Exception as e:
            print(f"Error removing temporary files: {e}")

def update_all():
    store_urls = stores_urls_ref.get()
    if not store_urls:
        return
    from concurrent.futures import as_completed
    store_items = list(store_urls.items())
    global_bar_lock = Lock()
    with tqdm(total=len(store_items), desc="All Stores", position=0) as global_bar:
        with ThreadPoolExecutor() as executor:
            futures = []
            for store_name, store_url in store_items:
                # Don't pass store_total_items here, handled in update_store
                futures.append(executor.submit(update_store, store_name, store_url))
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Store update generated an exception: {exc}")
                with global_bar_lock:
                    global_bar.update(1)

def add_store(store_name, store_url):
    stores_urls_ref.child(store_name).set(store_url)
    update_store(store_name, store_url)

def if_store_exists(store_name):
    return stores_urls_ref.child(store_name).get() is not None
    
def main():
    update_all()

if __name__ == "__main__":
    main()