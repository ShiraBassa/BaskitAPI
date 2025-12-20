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
    
    _raw_name_info = items_name_code_ref.get() or {}
    old_items_name_info = {
        k: v for k, v in _raw_name_info.items()
        if k and str(k).strip() and v and str(v).strip() and str(v).strip().lower() != "null"
    }

    main_bar = tqdm(
        total=len(stores), 
        desc="Updating Stores", 
        position=0, 
        leave=False, 
        dynamic_ncols=True, 
        bar_format=MAIN_BAR_FORMAT
        )
    pos = 1

    store_results = []
    with ThreadPoolExecutor() as executor:
        futures = []

        for store_name in stores:
            futures.append(
                executor.submit(update_store, store_name, handlers[store_name], pos, old_items_name_info)
            )
            pos += 1
        
        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    store_results.append(res)
            except Exception as exc:
                print(f"Branch update generated an exception: {exc}")
                traceback.print_exc()
            finally:
                main_bar.update(1)

    global_name_to_codes = {}
    global_name_store_branch_price = {}

    for (sname, name_to_codes, name_branch_price) in store_results:
        for n, codes in (name_to_codes or {}).items():
            global_name_to_codes.setdefault(n, set()).update(codes)

        for n, bmap in (name_branch_price or {}).items():
            if not bmap:
                continue
            sb = global_name_store_branch_price.setdefault(n, {})
            for b, p in bmap.items():
                sb[(sname, b)] = p

    CHUNK = 50000
    pending = {}

    pending_branch_updates = {}
    BRANCH_FLUSH_THRESHOLD = 20000
    pending_branch_count = 0

    def _flush_branch_updates():
        nonlocal pending_branch_updates, pending_branch_count
        for s, bmap in pending_branch_updates.items():
            for b, upd in bmap.items():
                if upd:
                    stores_items_ref.child(s).child(b).update(upd)
        pending_branch_updates = {}
        pending_branch_count = 0

    for n, codes in global_name_to_codes.items():
        sb_map = global_name_store_branch_price.get(n, {})
        if not sb_map:
            continue

        for (sname, b), p in sb_map.items():
            for code in codes:
                pending[f"{code}/{sname}/{b}"] = p

                # Mirror into stores_items/<store>/<branch>
                pending_branch_updates.setdefault(sname, {}).setdefault(b, {})[code] = p
                pending_branch_count += 1

                if len(pending) >= CHUNK:
                    items_stores_ref.update(pending)
                    pending = {}

                if pending_branch_count >= BRANCH_FLUSH_THRESHOLD:
                    _flush_branch_updates()

    if pending:
        items_stores_ref.update(pending)

    if pending_branch_count > 0:
        _flush_branch_updates()

    for bar in bars.values():
        bar.close()
    
    bars = {}
    main_bar.close()

def _fetch_and_parse_branch(store_name, branch_name, branch_url, store_handler, old_items_name_info):
    """Download a branch price file and parse it.

    Returns a tuple:
      (branch_name,
       branch_updates,                      # dict code->price for stores_items/<store>/<branch>
       items_store_path_updates,            # dict path->price for items_stores multi-update
       items_info_code_updates,             # dict code->name for items_code_name
       items_info_name_updates,             # dict name->code for items_name_code (only when new)
       name_to_codes,                       # dict name->set(codes) seen in this branch
       name_to_price)                       # dict name->price for THIS branch

    Does not write to Firebase.
    """
    gz_file_path = None
    xml_file_path = None
    zip_file_path = None

    while True:
        response = store_handler.session.get(branch_url, stream=True)

        if response.status_code == 200:
            content = response.content
            break

        if response.status_code == 403 and store_handler:
            new_url = store_handler.update_url(branch_name)
            if not new_url:
                return (branch_name, {}, {}, {}, {}, {}, {})
            stores_urls_ref.child(store_name).child(branch_name).set(new_url)
            branch_url = new_url
            continue

        return (branch_name, {}, {}, {}, {}, {}, {})

    if not content:
        return (branch_name, {}, {}, {}, {}, {}, {})

    try:
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
                    if file_name.endswith('.xml'):
                        with tempfile.NamedTemporaryFile(delete=False) as tmp_xml_file:
                            tmp_xml_file.write(zip_ref.read(file_name))
                            xml_file_path = tmp_xml_file.name
                        break
        else:  # xml
            with tempfile.NamedTemporaryFile(delete=False) as tmp_xml_file:
                tmp_xml_file.write(content)
                xml_file_path = tmp_xml_file.name

        if not xml_file_path:
            return (branch_name, {}, {}, {}, {}, {}, {})

        tree = ET.parse(xml_file_path)
        root = tree.getroot()

        branch_updates = {}
        items_store_path_updates = {}
        items_info_code_updates = {}
        items_info_name_updates = {}
        name_to_codes = {}
        name_to_price = {}

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
            if not item_code_from_xml or item_code_from_xml.lower() == 'null':
                continue

            try:
                price = float(price_text.strip())
            except Exception:
                continue

            item_name = sanitize_key(item_name_text) if item_name_text else None
            if not item_name or item_name == 'null' or item_name == '':
                continue

            # Determine canonical code if known, but KEEP the XML code too.
            canonical_code = old_items_name_info.get(item_name, item_code_from_xml)
            if canonical_code is None:
                continue

            canonical_code = str(canonical_code).strip()
            if not canonical_code or canonical_code.lower() == 'null':
                continue

            # Codes to keep for this name
            codes = {canonical_code, item_code_from_xml}

            # Keep code->name for BOTH codes
            for code in codes:
                if code and str(code).strip() and str(code).strip().lower() != 'null':
                    items_info_code_updates[code] = item_name

            # Keep name->code stable (only set if truly new)
            if item_name not in old_items_name_info and item_name not in items_info_name_updates:
                items_info_name_updates[item_name] = canonical_code

            # Record group membership + branch price for this name
            name_to_codes.setdefault(item_name, set()).update(codes)
            name_to_price[item_name] = price

            # Write the observed codes for this branch (initial write)
            for code in codes:
                branch_updates[code] = price
                items_store_path_updates[f"{code}/{store_name}/{branch_name}"] = price

        return (branch_name,
                branch_updates,
                items_store_path_updates,
                items_info_code_updates,
                items_info_name_updates,
                name_to_codes,
                name_to_price)

    finally:
        try:
            if gz_file_path and os.path.exists(gz_file_path):
                os.remove(gz_file_path)
            if xml_file_path and os.path.exists(xml_file_path):
                os.remove(xml_file_path)
            if zip_file_path and os.path.exists(zip_file_path):
                os.remove(zip_file_path)
        except Exception:
            pass

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
    
    # First pass: fetch+parse branches in parallel (no DB writes yet)
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_fetch_and_parse_branch, store_name, branch_name, branch_url, hanlder, old_items_name_info)
            for branch_name, branch_url in branch_urls
        ]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                print(f"Branch update generated an exception: {exc}")
                traceback.print_exc()
            finally:
                bars[store_name].update(1)

    # Second pass: write observed data + build global name-groups for mirroring
    all_items_store_updates = {}
    all_code_name_updates = {}
    all_name_code_updates = {}

    # name -> set(codes)
    global_name_to_codes = {}
    # name -> branch -> price
    global_name_branch_price = {}
    # branch -> set(existing codes already written)
    existing_codes_per_branch = {}

    for (branch_name,
         branch_updates,
         items_store_path_updates,
         items_info_code_updates,
         items_info_name_updates,
         name_to_codes,
         name_to_price) in results:

        if branch_updates:
            stores_items_ref.child(store_name).child(branch_name).update(branch_updates)
            existing_codes_per_branch.setdefault(branch_name, set()).update(branch_updates.keys())

        if items_store_path_updates:
            all_items_store_updates.update(items_store_path_updates)

        if items_info_code_updates:
            all_code_name_updates.update(items_info_code_updates)

        if items_info_name_updates:
            # do not overwrite if already known
            for n, c in items_info_name_updates.items():
                if n not in old_items_name_info and n not in all_name_code_updates:
                    all_name_code_updates[n] = c

        for n, codes in (name_to_codes or {}).items():
            global_name_to_codes.setdefault(n, set()).update(codes)

        for n, price in (name_to_price or {}).items():
            global_name_branch_price.setdefault(n, {})[branch_name] = price

    # Bulk DB writes (observed)
    if all_items_store_updates:
        items_stores_ref.update(all_items_store_updates)

    if all_code_name_updates:
        items_code_name_ref.update(all_code_name_updates)

    if all_name_code_updates:
        items_name_code_ref.update(all_name_code_updates)

    # Third pass: FULL MIRRORING (LOCAL, per store)
    # For each name, ensure EVERY code has EVERY branch price for that name.
    mirror_items_store_updates = {}
    mirror_branch_updates = {}

    for n, codes in global_name_to_codes.items():
        branch_price = global_name_branch_price.get(n, {})
        if not branch_price:
            continue

        for b, p in branch_price.items():
            for code in codes:
                # Mirror into items_stores
                mirror_items_store_updates[f"{code}/{store_name}/{b}"] = p

                # Mirror into stores_items/<store>/<branch>
                existing = existing_codes_per_branch.get(b, set())
                if code not in existing:
                    mirror_branch_updates.setdefault(b, {})[code] = p

    # Apply mirrored branch updates (per branch)
    for b, upd in mirror_branch_updates.items():
        if upd:
            stores_items_ref.child(store_name).child(b).update(upd)

    # Apply mirrored items_stores updates (chunk if huge)
    if mirror_items_store_updates:
        # Chunk large multi-location updates to avoid request size limits
        items = list(mirror_items_store_updates.items())
        CHUNK = 50000
        for i in range(0, len(items), CHUNK):
            items_stores_ref.update(dict(items[i:i+CHUNK]))

    # Return per-store mirroring data for global mirroring
    return (store_name, global_name_to_codes, global_name_branch_price)

def update_branch(store_name, branch_name, branch_url, store_handler, old_items_name_info=None):
    gz_file_path = None
    xml_file_path = None
    zip_file_path = None
    
    if store_handler and not hasattr(store_handler, "_search_bars"):
        store_handler._search_bars = {}
        
    while True:
        response = store_handler.session.get(branch_url, stream=True)

        if response.status_code == 200:
            content = response.content
            break

        if response.status_code == 403 and store_handler:
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

    if old_items_name_info is None:
        _raw_name_info = items_name_code_ref.get() or {}
        old_items_name_info = {
            k: v for k, v in _raw_name_info.items()
            if k and str(k).strip() and v and str(v).strip() and str(v).strip().lower() != "null"
        }

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
        if not item_code_from_xml or item_code_from_xml.lower() == "null":
            continue
        try:
            price = float(price_text.strip())
        except Exception:
            continue

        item_name = sanitize_key(item_name_text) if item_name_text else None

        if not item_name or item_name == "null" or item_name == "":
            continue

        canonical_code = item_code_from_xml

        if item_name:
            if item_name in old_items_name_info and old_items_name_info.get(item_name):
                canonical_code = old_items_name_info[item_name]
                items_info_code_updates[canonical_code] = item_name
                items_info_name_updates[item_name] = canonical_code

                if item_code_from_xml != canonical_code:
                    # Keep BOTH codes: write mappings for the XML code too
                    items_info_code_updates[item_code_from_xml] = item_name
            else:
                if item_name not in old_items_name_info and item_name not in items_info_name_updates:
                    items_info_name_updates[item_name] = item_code_from_xml
                if item_code_from_xml not in items_info_code_updates:
                    items_info_code_updates[item_code_from_xml] = item_name

        if canonical_code is None:
            continue

        canonical_code = str(canonical_code).strip()
        if not canonical_code or canonical_code.lower() == "null":
            continue

        # Always store under the canonical code
        branch_updates[canonical_code] = price
        items_store_path_updates[f"{canonical_code}/{store_name}/{branch_name}"] = price

        # If the XML code is different, also store under the XML code (keep both codes alive)
        if item_code_from_xml != canonical_code:
            branch_updates[item_code_from_xml] = price
            items_store_path_updates[f"{item_code_from_xml}/{store_name}/{branch_name}"] = price

    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if items_store_path_updates:
        items_stores_ref.update(items_store_path_updates)

    if items_info_code_updates:
        items_code_name_ref.update(items_info_code_updates)

    if items_info_name_updates:
        items_name_code_ref.update(items_info_name_updates)

    try:
        if gz_file_path and os.path.exists(gz_file_path):
            os.remove(gz_file_path)
        if xml_file_path and os.path.exists(xml_file_path):
            os.remove(xml_file_path)
        if zip_file_path and os.path.exists(zip_file_path):
            os.remove(zip_file_path)
    except Exception as e:
        print(f"Error removing temporary files: {e}")

    return True


def add_branch(store_name, branch_name, store_handler):
    branch_url = store_handler.branches[branch_name]["url"]
    stores_urls_ref.child(store_name).child(branch_name).set(branch_url)

    # Use cached name->code map for correct canonicalization
    _raw_name_info = items_name_code_ref.get() or {}
    old_items_name_info = {
        k: v for k, v in _raw_name_info.items()
        if k and str(k).strip() and v and str(v).strip() and str(v).strip().lower() != "null"
    }

    (b,
     branch_updates,
     items_store_path_updates,
     items_info_code_updates,
     items_info_name_updates,
     _name_to_codes,
     _name_to_price) = _fetch_and_parse_branch(store_name, branch_name, branch_url, store_handler, old_items_name_info)

    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if items_store_path_updates:
        items_stores_ref.update(items_store_path_updates)

    if items_info_code_updates:
        items_code_name_ref.update(items_info_code_updates)

    if items_info_name_updates:
        items_name_code_ref.update(items_info_name_updates)

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