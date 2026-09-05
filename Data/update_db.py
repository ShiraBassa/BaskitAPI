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
from Classes.aiHandler import *
import re
import requests


STORES_CHUNK_SIZE = 5
ITEMS_CHUNK_SIZE = 100000


bars = {}

global_grouped_updates = {}
global_code_seen_groups = {}

def update_all_stores(handlers):
    global bars
    bars = {}

    global global_grouped_updates
    global_grouped_updates = {}
    global global_code_seen_groups
    global_code_seen_groups = {}

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

    store_results = []
    with ThreadPoolExecutor() as executor:
        futures = []

        for store_name in handlers.keys():
            futures.append(
                executor.submit(update_store, store_name, handlers[store_name], pos, None)
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

    # Rebuild ALL groups globally only once after every branch finished
    if global_grouped_updates:
        rebuilt_groups = {
            base: sorted(list(codes))
            for base, codes in global_grouped_updates.items()
            if codes
        }

        groups_ref.set(rebuilt_groups)

    for bar in bars.values():
        bar.close()

    bars = {}
    main_bar.close()

def _fetch_and_parse_branch(store_name, branch_name, branch_url, store_handler):
    gz_file_path = None
    xml_file_path = None
    zip_file_path = None

    while True:
        try:
            response = store_handler.session.get(
                branch_url,
                stream=True,
                timeout=(10, 30)
            )
        except requests.exceptions.Timeout:
            print(f"Timeout while fetching {store_name} -> {branch_name}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Request failed {store_name} -> {branch_name}: {e}")
            return None

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
            return (branch_name, {}, {}, {}, {})

        tree = ET.parse(xml_file_path)
        root = tree.getroot()

        branch_updates = {}
        items_store_path_updates = {}
        items_info_code_updates = {}
        grouped_updates = {}


        # Safety: detect inconsistent normalization for the same item code
        code_to_base_check = {}

        items = list(root.findall('.//{*}Items/{*}Item'))

        for item in items:
            item_code_text = item.findtext('{*}ItemCode')
            price_text = item.findtext('{*}ItemPrice')
            item_name_text = (
                item.findtext('{*}ItemName')
                or item.findtext('{*}ItemNm')
                or item.findtext('{*}ItemDesc')
                or item.findtext('{*}ItemDescription')
            )
            weight_text = item.findtext('{*}Quantity')
            unit_text = item.findtext('{*}UnitQty')
            item_type = item.findtext('{*}ItemType')

            if item_type and item_type not in {"0", "1", "2"}:
                continue

            if not item_code_text or not price_text:
                continue

            item_code = str(item_code_text.strip())
            if not item_code or item_code == "null":
                continue

            try:
                price = float(price_text.strip())
            except Exception:
                continue

            item_name = item_name_text if item_name_text else None
            if not item_name or item_name == 'null' or item_name == '':
                continue

            # Parse item weight before using it
            if weight_text and str(weight_text).strip():
                raw_weight = str(weight_text).strip()
                try:
                    num = float(raw_weight)
                    if num.is_integer():
                        item_weight = str(int(num))
                    else:
                        item_weight = str(num).rstrip('0').rstrip('.')
                except Exception:
                    item_weight = raw_weight
            else:
                item_weight = "unknown"

            normalized = regulate_single_item_name(item_name)
            if not normalized:
                continue

            base = normalized["base"]
            company = normalized["company"]

            # Remove trailing numeric weight from name if it matches parsed item_weight
            if base and item_weight and item_weight != "unknown":
                weight_str = str(item_weight)
                base = re.sub(rf"\s+{re.escape(weight_str)}\s*$", "", base).strip()

            if not base:
                continue

            # Ensure every item code always uses ONE canonical normalized base
            if item_code in code_to_base_check:
                existing_base = code_to_base_check[item_code]

                if existing_base != base:
                    print(
                        f"[Normalization conflict resolved] code={item_code} "
                        f"'{existing_base}' kept over '{base}' "
                        f"(store={store_name}, branch={branch_name})"
                    )

                # Never allow the same code to change groups later in parsing
                base = existing_base
            else:
                code_to_base_check[item_code] = base

            branch_updates[item_code] = price
            items_store_path_updates[f"{item_code}/{store_name}/{branch_name}"] = price

            item_unit = str(unit_text).strip() if unit_text and str(unit_text).strip() else "יחידות"
            unit_clean = str(item_unit).strip().lower()
            normalized_unit, item_weight = _get_normalized_unit(unit_clean, item_weight)

            safe_base = sanitize_key(str(base)).strip()

            # Grouping must use ONLY exact normalized names
            # Never merge because one name contains another
            canonical_group_name = safe_base

            item_info = {
                "name": canonical_group_name
            }

            if item_weight and item_weight != "unknown":
                item_info["weight"] = item_weight

            if normalized_unit and normalized_unit != "unknown":
                item_info["unit"] = normalized_unit

            if company and company != "unknown":
                item_info["company"] = company


            items_info_code_updates[item_code] = item_info
            if canonical_group_name:
                existing_codes = grouped_updates.setdefault(canonical_group_name, [])

                if item_code not in existing_codes:
                    existing_codes.append(item_code)

        return (branch_name,
                branch_updates,
                items_store_path_updates,
                items_info_code_updates,
                grouped_updates)

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
    safe_store_name = sanitize_key(store_name)
    branch_data = stores_urls_ref.child(safe_store_name).get()

    if not branch_data:
        print(f"Skipping {store_name}: no branch data found")
        return store_name, {}, {}

    branch_urls = list(branch_data.items())

    bars[store_name] = tqdm(
        total=len(branch_urls),
        desc=store_name[::-1],
        position=pos,
        leave=False,
        dynamic_ncols=True,
        bar_format=STORE_BAR_FORMAT
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []

        for branch_name, branch_url in branch_urls:
            futures.append(
                executor.submit(
                    update_branch,
                    store_name,
                    branch_name,
                    branch_url,
                    hanlder,
                    None
                )
            )

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"Branch update generated an exception: {exc}")
                traceback.print_exc()
            finally:
                bars[store_name].update(1)

    return (store_name, {}, {})

def update_branch(store_name, branch_name, branch_url, store_handler, old_items_name_info=None):
    # Handler/session validation
    result = _fetch_and_parse_branch(store_name, branch_name, branch_url, store_handler)

    if not result:
        return False

    (b,
     branch_updates,
     items_store_path_updates,
     items_info_code_updates,
     grouped_updates) = result

    if branch_updates:
        stores_items_ref.child(store_name).child(branch_name).update(branch_updates)

    if grouped_updates:
        global global_grouped_updates
        global global_code_seen_groups

        for base, codes in grouped_updates.items():
            safe_base = sanitize_key(str(base)).strip()

            if not safe_base:
                continue

            global_grouped_updates.setdefault(safe_base, set())

            for code in codes:
                code_str = str(code).strip()

                if not code_str:
                    continue

                # If this code already belongs to another exact group,
                # keep ONLY the first exact normalized group name.
                if code_str in global_code_seen_groups:
                    existing_group = global_code_seen_groups[code_str]

                    if existing_group != safe_base:
                        continue
                else:
                    global_code_seen_groups[code_str] = safe_base

                global_grouped_updates[safe_base].add(code_str)

    if items_store_path_updates:
        items_stores_ref.update(items_store_path_updates)

    if items_info_code_updates:
        safe_updates = {}

        existing_items_info = items_info_ref.get() or {}

        for item_code, item_info in items_info_code_updates.items():
            if not isinstance(item_info, dict):
                continue

            existing_item_info = existing_items_info.get(str(item_code), {})
            canonical_name = global_code_seen_groups.get(str(item_code))

            if canonical_name:
                item_info["name"] = canonical_name

            if (
                isinstance(existing_item_info, dict)
                and existing_item_info.get("category")
                and not item_info.get("category")
            ):
                item_info["category"] = existing_item_info.get("category")

            for key, value in item_info.items():
                safe_updates[f"{item_code}/{key}"] = value

        if safe_updates:
            items_info_ref.update(safe_updates)

    return True


def add_branch(store_name, branch_name, store_handler):
    branch_url = store_handler.branches[branch_name]["url"]
    stores_urls_ref.child(store_name).child(branch_name).set(branch_url)

    return update_branch(
        store_name,
        branch_name,
        branch_url,
        store_handler,
        None
    )

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
        items = items_info_ref.get()

        if items:
            item_keys = list(items.keys())

            for i in range(0, len(item_keys), ITEMS_CHUNK_SIZE):
                chunk = item_keys[i:i + ITEMS_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                items_info_ref.update(delete_dict)

            items_info_ref.delete()

    except Exception as e:
        print(f"Error clearing items: {e}")


    try:
        groups = groups_ref.get()

        if groups:
            groups = list(groups.keys())

            for i in range(0, len(groups), ITEMS_CHUNK_SIZE):
                chunk = groups[i:i + ITEMS_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                groups_ref.update(delete_dict)

            groups_ref.delete()

    except Exception as e:
        print(f"Error clearing items: {e}")
    
def remove_all():
    clear_all()
    stores_urls_ref.delete()

    try:
        items = items_info_ref.get()

        if items:
            item_keys = list(items.keys())

            for i in range(0, len(item_keys), ITEMS_CHUNK_SIZE):
                chunk = item_keys[i:i + ITEMS_CHUNK_SIZE]
                delete_dict = {key: None for key in chunk}
                items_info_ref.update(delete_dict)

            items_info_ref.delete()

    except Exception as e:
        print(f"Error clearing info code: {e}")


def get_categories(item_codes, async_mode=False):
    if not item_codes:
        return {}

    item_codes_set = {str(c) for c in item_codes}

    aiHandler = AIHandler(list(item_codes_set))

    if async_mode:
        aiHandler.run_async()
        return {}

    classified = aiHandler.classify_items()

    if not isinstance(classified, dict):
        return {}

    return {
        str(code): category
        for code, category in classified.items()
        if str(code) in item_codes_set
    }