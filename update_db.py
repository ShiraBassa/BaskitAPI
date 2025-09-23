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
import zipfile


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
    
    with tqdm(total=len(branch_urls), desc=store_name, ncols=100,
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}", position=0, leave=True) as global_bar:
        with ThreadPoolExecutor() as executor:
            futures = []
            for branch_name, branch_url in branch_urls:
                futures.append(
                    executor.submit(update_branch, store_name, branch_name, branch_url, hanlder, global_bar_lock, global_bar)
                )
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Branch update generated an exception: {exc}")
                    traceback.print_exc()  # full stack trace

def update_branch(store_name, branch_name, branch_url, store_handler, global_bar_lock, global_bar):
    gz_file_path = None
    xml_file_path = None
    file_num = 0
    total_files = None
    branch_bar = None
    
    # Initialize branch progress bars dict
    if store_handler and not hasattr(store_handler, "_search_bars"):
        store_handler._search_bars = {}
        
    # Create branch-level progress bar
    if store_handler:
        branch_bar = store_handler._search_bars[branch_name] = tqdm(
            total=None,
            desc=f"\t{branch_name[::-1]} - searching files",
            position=1,
            ncols=90,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}",
            leave=False
        )

    while True:
        response = requests.get(branch_url, stream=True)

        if response.status_code == 403 and store_handler:
            new_url = store_handler.update_url(branch_name)
            stores_urls_ref.child(store_name).child(branch_name).set(new_url)
            branch_url = new_url
            continue

        elif response.status_code == 404 and store_handler:
            success, total_files = store_handler.set_branch_single(
                branch_name,
                store_handler.branches[branch_name]["type"],
                file_number=file_num
            )
            
            # Use 'is not None' to check for the bar's existence
            if branch_bar is not None and branch_bar.total is None and total_files:
                branch_bar.total = total_files
                branch_bar.refresh()
            
            file_num += 1
            if branch_bar is not None:
                branch_bar.update(1)
                branch_bar.set_description_str(f"\t{branch_name[::-1]} - searching files {file_num}/{total_files or '?'}")
                branch_bar.refresh()

            if not success:
                break
            
            continue
        
        else:
            content = response.content
            break

    # After the while loop, safely close the bar and update the global bar
    if branch_bar is not None:
        branch_bar.close()

        if branch_name in store_handler._search_bars:
            del store_handler._search_bars[branch_name]
    
    # Only increment main store bar once per branch, after the branch is fully handled
    if global_bar and global_bar_lock:
        with global_bar_lock:
            global_bar.update(1)

    if 'content' not in locals():
        return

    if content[:2] == b'\x1f\x8b':  # gz
        with tempfile.NamedTemporaryFile(delete=False) as tmp_gz_file:
            tmp_gz_file.write(content)
            gz_file_path = tmp_gz_file.name

        with gzip.open(gz_file_path, 'rb') as f_in:
            with tempfile.NamedTemporaryFile(delete=False) as tmp_xml_file:
                tmp_xml_file.write(f_in.read())
                xml_file_path = tmp_xml_file.name

    elif content[:2] == b'PK':  # zip
        with tempfile.NamedTemporaryFile(delete=False) as tmp_zip_file:
            tmp_zip_file.write(content)
            zip_file_path = tmp_zip_file.name

        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(".xml"):
                    with tempfile.NamedTemporaryFile(delete=False) as tmp_xml_file:
                        tmp_xml_file.write(zip_ref.read(file_name))
                        xml_file_path = tmp_xml_file.name
                    break
    else:  # xml
        with tempfile.NamedTemporaryFile(delete=False) as tmp_xml_file:
            tmp_xml_file.write(content)
            xml_file_path = tmp_xml_file.name

    tree = ET.parse(xml_file_path)
    root = tree.getroot()

    branch_updates = {}
    item_updates = {}
    old_items = items_stores_ref.get() or {}
    old_branch = stores_items_ref.child(store_name).child(branch_name).get() or {}
    
    items = list(root.findall('./Items/Item'))
    
    for item in items:
        item_name = item.find('ItemCode').text.strip()
        price = float(item.find('ItemPrice').text.strip())

        if item_name is None or price is None:
            continue

        if item_name in old_branch:
            if old_branch[item_name] != price:
                branch_updates[item_name] = price
        else:
            branch_updates[item_name] = price

        if item_name in old_items:
            item_updates[item_name] = dict(old_items[item_name])

            if store_name in item_updates[item_name]:
                if branch_name in item_updates[item_name][store_name] and \
                    item_updates[item_name][store_name][branch_name] == price:
                    continue
            else:
                item_updates[item_name][store_name] = {}
            
            item_updates[item_name][store_name] = dict(item_updates[item_name][store_name])
            item_updates[item_name][store_name][branch_name] = price

        else:
            item_updates[item_name] = {
                store_name: {
                    branch_name: price
                }
            }

    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if item_updates:
        items_stores_ref.update(item_updates)
    
    try:
        if gz_file_path and os.path.exists(gz_file_path):
            os.remove(gz_file_path)
        if xml_file_path and os.path.exists(xml_file_path):
            os.remove(xml_file_path)
    except Exception as e:
        print(f"Error removing temporary files: {e}")

def add_branch(store_name, branch_name, branch_url, store_handler, global_bar, global_bar_lock):
    stores_urls_ref.child(store_name).child(branch_name).set(branch_url)
    update_branch(store_name, branch_name, branch_url, store_handler, global_bar_lock, global_bar)

def if_branch_exists(store_name, branch_name):
    return stores_urls_ref.child(store_name).child(branch_name).get() is not None

def clear_all():
    stores_items_ref.delete()
    items_stores_ref.delete()
    
def remove_all():
    clear_all()
    stores_urls_ref.delete()