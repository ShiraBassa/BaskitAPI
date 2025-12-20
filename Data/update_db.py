import gzip
import xml.etree.ElementTree as ET
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from concurrent.futures import as_completed
import traceback
import zipfile
from Data.data_sets import *
from RequestClasses.generalRequestsFns import sanitize_key


STORES_CHUNK_SIZE = 5
ITEMS_CHUNK_SIZE = 100000

bars = {}

def update_all_stores(handlers):
    global bars
    bars = {}

    stores = stores_urls_ref.get()

    if not stores:
        return
    
    old_items_name_info = items_name_code_ref.get() or {}

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
            futures.append(
                executor.submit(update_store, store_name, handlers[store_name], pos, old_items_name_info)
            )
            pos += 1
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"Branch update generated an exception: {exc}")
                traceback.print_exc()
            finally:
                main_bar.update(1)
        
    for bar in bars.values():
        bar.close()
    
    bars = {}
    main_bar.close()

def update_store(store_name, hanlder, pos, old_items_name_info):
    branch_urls = list(stores_urls_ref.child(store_name).get().items())
    bars[store_name] = tqdm(
        total=len(branch_urls), 
        desc=store_name[::-1],
        position=pos, 
        leave=False,
        dynamic_ncols=True, 
        bar_format=STORE_BAR_FORMAT
        )
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(update_branch, store_name, branch_name, branch_url, hanlder, old_items_name_info)
            for branch_name, branch_url in branch_urls
        ]

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"Branch update generated an exception: {exc}")
                traceback.print_exc()
            finally:
                bars[store_name].update(1)

def update_branch(store_name, branch_name, branch_url, store_handler, old_items_name_info=None):
    gz_file_path = None
    xml_file_path = None
    
    if store_handler and not hasattr(store_handler, "_search_bars"):
        store_handler._search_bars = {}
        
    while True:
        response = store_handler.session.get(branch_url, stream=True)

        if response.status_code == 200:
            content = response.content
            break

        if (response.status_code == 403 or response.status_code == 200) and store_handler:
            new_url = store_handler.update_url(branch_name)
            
            if not new_url:
                #!!!!!!!skipping the branch!!!!!!
                return False
            
            stores_urls_ref.child(store_name).child(branch_name).set(new_url)
            branch_url = new_url
            continue

        if response.status_code == 404:
            return False
        
        return False
    
    if content is None:
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
    items_store_path_updates = {}
    items_info_code_updates = {}
    items_info_name_updates = {}
    ignored_codes = set()

    if old_items_name_info is None:
        old_items_name_info = items_name_code_ref.get() or {}

    items = list(root.findall('.//{*}Items/{*}Item'))
                
    for item in items:
        if item is None:
            break

        item_code_text = item.findtext('{*}ItemCode')
        price_text = item.findtext('{*}ItemPrice')
        item_name_text = item.findtext('{*}ItemName')

        if not item_code_text or not price_text:
            continue

        item_code_from_xml = item_code_text.strip()
        try:
            price = float(price_text.strip())
        except Exception:
            continue

        item_name = sanitize_key(item_name_text) if item_name_text else None

        if not item_name or item_name == "null" or item_name == "":
            continue

        canonical_code = item_code_from_xml

        if item_name:
            if item_name in old_items_name_info:
                canonical_code = old_items_name_info[item_name]
                items_info_code_updates[canonical_code] = item_name
                items_info_name_updates[item_name] = canonical_code

                if item_code_from_xml != canonical_code:
                    items_info_code_updates[item_code_from_xml] = None
                    ignored_codes.add(item_code_from_xml)
            else:
                if item_name not in items_info_name_updates:
                    items_info_name_updates[item_name] = item_code_from_xml
                if item_code_from_xml not in items_info_code_updates:
                    items_info_code_updates[item_code_from_xml] = item_name

        branch_updates[canonical_code] = price

        # Store the price under the canonical code, without reading/merging the entire DB.
        items_store_path_updates[f"{canonical_code}/{store_name}/{branch_name}"] = price

    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if ignored_codes:
        stores_items_ref.child(store_name).child(branch_name).update({code: None for code in ignored_codes})

    if items_store_path_updates:
        items_stores_ref.update(items_store_path_updates)

    if ignored_codes:
        delete_paths = {
            f"{code}/{store_name}/{branch_name}": None
            for code in ignored_codes
        }
        items_stores_ref.update(delete_paths)

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

    if not update_branch(store_name, branch_name, branch_url, store_handler, None):
        return False

    return True

def if_branch_exists(store_name, branch_name):
    in_items = if_exists_in_db(store_name, branch_name)
    in_urls = stores_urls_ref.child(store_name).child(branch_name).get() is not None
    
    return in_items and in_urls

def if_exists_in_db(store_name, branch_name):
    store_ref = stores_items_ref.child(store_name)

    if store_ref.get() is None:
        return False
    
    return store_ref.child(branch_name).get() is not None

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
        print(f"Error clearing items: {e}")

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