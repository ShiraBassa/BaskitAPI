import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Data.update_db import *
from Data.update_db import update_all_stores
from Classes.msgBarHandler import msg_bar
from RequestClasses.generalRequestsFns import sanitize_key
from firebase_admin import db
def clear_generated_databases():
    print("Clearing generated databases...")

    try:
        groups_ref.set({})
        print("Cleared groups database")
    except Exception as e:
        print(f"Failed clearing groups database: {e}")

    try:
        stores_items_ref.set({})
        print("Cleared stores_items database")
    except Exception as e:
        print(f"Failed clearing stores_items database: {e}")

    try:
        items_stores_ref.set({})
        print("Cleared items_stores database")
    except Exception as e:
        print(f"Failed clearing items_stores database: {e}")

    try:
        stores_branches_ref.set({})
        print("Cleared stores_branches database")
    except Exception as e:
        print(f"Failed clearing stores_branches database: {e}")

def safely_populate_categories():
    items = items_info_ref.get() or {}

    if not items:
        print("No items found for category population.")
        return

    item_codes = list(items.keys())

    print(f"Preparing categories for {len(item_codes)} items...")

    existing_categories = items_categories_ref.get() or {}

    missing_category_codes = []

    for item_code in item_codes:
        existing_category = existing_categories.get(item_code)

        if existing_category:
            continue

        missing_category_codes.append(item_code)

    print(
        f"Items already categorized: "
        f"{len(item_codes) - len(missing_category_codes)}"
    )

    print(f"Missing categories: {len(missing_category_codes)}")

    if not missing_category_codes:
        print("All items already have categories.")
        return

    print("Generating categories only for missing items...")

    get_categories(missing_category_codes)

def set_all_stores(stores_branches):
    handlers = {}

    for store_name in stores_branches.keys():
        config = STORE_CONFIG.get(store_name)
        if not config:
            continue

        store_class = config["class"]

        try:
            handler_args = {
                "_store_name": store_name,
                "_site_url": config.get("base"),
                "_main_page": config.get("main_page"),
                "_download_url": config.get("download_url"),
                "_extra_pages": config.get("extra_pages"),
                "_extra_vars": config.get("extra_vars")
            }

            handler_args = {
                k: v
                for k, v in handler_args.items()
                if v is not None
            }

            handler = store_class(**handler_args)

            if handler and handler.all_branches:
                handlers[store_name] = handler

                branches_dict = handler.get_all_branches() or {}

                stores_branches_ref.child(
                    sanitize_key(store_name)
                ).set(branches_dict)

                valid_branches = [
                    branch
                    for branch in stores_branches[store_name]
                    if branch in handler.all_branches
                ]

                missing_branches = set(stores_branches[store_name]) - set(valid_branches)

                if missing_branches:
                    print(
                        f"Skipping stale branches for {store_name}: "
                        f"{list(missing_branches)}"
                    )

                handler.set_branches(valid_branches)

                update_branches_urls(
                    store_name,
                    handler,
                    valid_branches
                )

        except Exception as e:
            print(f"Failed creating handler for {store_name}: {e}")

    return handlers

def get_all_existing_stores():
    stores_branches = {}
    stores_urls = stores_urls_ref.get()

    if not stores_urls:
        return {}

    for store_name in stores_urls:
        stores_branches[store_name] = []
        
        for branch_name in stores_urls[store_name]:
            stores_branches[store_name].append(branch_name)

    return stores_branches

def update_branches_urls(store_name, store_handler, branches):
    for branch in branches:
        branch_data = store_handler.branches.get(branch)

        if not branch_data:
            print(f"Missing branch in handler: {store_name} -> {branch}")
            continue

        url = branch_data.get("url")

        if url:
            stores_urls_ref.child(store_name).child(branch).set(url)


def main():
    print("\033c", end="")
    clear_generated_databases()

    stores_branches = get_all_existing_stores()
    msg_bar_handler = msg_bar(len(stores_branches) + 2)

    handlers = set_all_stores(stores_branches)
    update_all_stores(handlers)

    safely_populate_categories()

    msg_bar_handler.close()

if __name__ == "__main__":
    main()