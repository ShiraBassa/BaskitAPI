import gzip
import xml.etree.ElementTree as ET
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from concurrent.futures import as_completed
import traceback
import zipfile
from data_sets import *
from generalRequestsFns import sanitize_key


bars = {}

def update_all_stores(handlers):
    global bars
    bars = {}

    stores = stores_urls_ref.get()

    if not stores:
        return
    
    main_bar = tqdm(
        total=len(stores), 
        desc="Updating Stores", 
        position=0, 
        leave=False, 
        dynamic_ncols=True, 
        bar_format=MAIN_BAR_FORMAT
        )
    pos = 1

    with ThreadPoolExecutor() as executor:
        futures = []

        for store_name in stores:
            branch_urls = list(stores_urls_ref.child(store_name).get().items())
            bars[store_name] = tqdm(
                total=len(branch_urls), 
                desc=store_name,
                position=pos, 
                leave=False, 
                dynamic_ncols=True, 
                bar_format=STORE_BAR_FORMAT
                )
            pos += 1

            futures.append(
                executor.submit(update_store, store_name, handlers[store_name], branch_urls)
            )
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"Branch update generated an exception: {exc}")
                traceback.print_exc()  # full stack trace
            finally:
                # Refresh the bar for each finished branch
                main_bar.update(1)
        
    for bar in bars.values():
        bar.close()
    
    bars = {}
    main_bar.close()

def update_store(store_name, hanlder, branch_urls):
    for branch_name, branch_url in branch_urls:
        update_branch(store_name, branch_name, branch_url, hanlder)
        bars[store_name].update(1)

def update_branch(store_name, branch_name, branch_url, store_handler):
    gz_file_path = None
    xml_file_path = None
    
    # Initialize branch progress bars dict
    if store_handler and not hasattr(store_handler, "_search_bars"):
        store_handler._search_bars = {}
        
    while True:
        response = store_handler.session.get(branch_url, stream=True)

        if response.status_code == 403 and store_handler:
            new_url = store_handler.update_url(branch_name)
            stores_urls_ref.child(store_name).child(branch_name).set(new_url)
            branch_url = new_url
            continue

        elif response.status_code == 404:
            return False
        
        else:
            content = response.content
            break
    
    if 'content' not in locals():
        return False
    
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
    items_info_code_updates = {}
    items_info_name_updates = {}
    old_items = items_stores_ref.get() or {}
    old_branch = stores_items_ref.child(store_name).child(branch_name).get() or {}
    old_items_code_info = items_code_name_ref.get() or {}
    old_items_name_info = items_name_code_ref.get() or {}
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]

    # Now you can safely find ItemName
    items = list(root.findall('./Items/Item'))
                
    for item in items:
        item_code = item.find('ItemCode').text.strip()
        price = float(item.find('ItemPrice').text.strip())
        item_name = item.find('ItemName')
        
        if item_code is None or price is None:
            continue

        if item_name is not None:
            item_name = sanitize_key(item_name.text)

        if item_code in old_branch:
            if old_branch[item_code] != price:
                branch_updates[item_code] = price
        else:
            branch_updates[item_code] = price

        if item_code in old_items:
            item_updates[item_code] = dict(old_items[item_code])

            if store_name in item_updates[item_code]:
                if branch_name in item_updates[item_code][store_name] and \
                    item_updates[item_code][store_name][branch_name] == price:
                    continue
            else:
                item_updates[item_code][store_name] = {}
            
            item_updates[item_code][store_name] = dict(item_updates[item_code][store_name])
            item_updates[item_code][store_name][branch_name] = price

        else:
            item_updates[item_code] = {
                store_name: {
                    branch_name: price
                }
            }
            
        if item_name and item_code and item_code not in old_items_code_info:
            items_info_code_updates[item_code] = item_name

        if item_name and item_code and item_name not in old_items_name_info:
            items_info_name_updates[item_name] = item_code


    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if item_updates:
        items_stores_ref.update(item_updates)
    
    if items_info_code_updates:
        items_code_name_ref.update(items_info_code_updates)
    
    if items_info_name_updates:
        items_name_code_ref.update(items_info_name_updates)

    try:
        if gz_file_path and os.path.exists(gz_file_path):
            os.remove(gz_file_path)
        if xml_file_path and os.path.exists(xml_file_path):
            os.remove(xml_file_path)
    except Exception as e:
        print(f"Error removing temporary files: {e}")

    return True


def add_branch(store_name, branch_name, store_handler):
    branch_url = store_handler.branches[branch_name]["url"]
    stores_urls_ref.child(store_name).child(branch_name).set(branch_url)

    if not update_branch(store_name, branch_name, branch_url, store_handler):
        return False

    return True

def if_branch_exists(store_name, branch_name):
    return stores_urls_ref.child(store_name).child(branch_name).get() is not None

STORES_CHUNK_SIZE = 5
ITEMS_CHUNK_SIZE = 100000

def clear_all():
    try:
        stores = stores_items_ref.get()

        if stores:
            store_keys = list(stores.keys())

            for i in range(0, len(store_keys), STORES_CHUNK_SIZE):
                chunk = store_keys[i:i + STORES_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                stores_items_ref.update(delete_dict)

            stores_items_ref.delete()

    except Exception as e:
        print(f"Error clearing stores: {e}")

    try:
        items = items_stores_ref.get()

        if items:
            item_keys = list(items.keys())

            for i in range(0, len(item_keys), ITEMS_CHUNK_SIZE):
                chunk = item_keys[i:i + ITEMS_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                items_stores_ref.update(delete_dict)

            items_stores_ref.delete()

    except Exception as e:
        print(f"Error clearing items: {e}")
    
def remove_all():
    clear_all()
    stores_urls_ref.delete()

    try:
        items = items_code_name_ref.get()

        if items:
            item_keys = list(items.keys())

            for i in range(0, len(item_keys), ITEMS_CHUNK_SIZE):
                chunk = item_keys[i:i + ITEMS_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                items_code_name_ref.update(delete_dict)

            items_code_name_ref.delete()

    except Exception as e:
        print(f"Error clearing info code: {e}")

    try:
        items = items_name_code_ref.get()

        if items:
            item_keys = list(items.keys())

            for i in range(0, len(item_keys), ITEMS_CHUNK_SIZE):
                chunk = item_keys[i:i + ITEMS_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                items_name_code_ref.update(delete_dict)

            items_name_code_ref.delete()

    except Exception as e:
        print(f"Error clearing info name: {e}")