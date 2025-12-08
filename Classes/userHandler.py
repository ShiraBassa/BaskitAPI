from Data.data_sets import *
from RequestClasses.generalRequestsFns import getCities
import Data.update_db as update_db
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
import traceback


bars = {}

class User():
    def __init__(self, user_id=None, is_admin=False):
        self.user_id = user_id
        self.is_admin = is_admin  # Flag to distinguish admin users
        self.cities = []
        self.choices = {}
        self.handlers = {}

        # Only load from Firebase if it's a regular user
        if not is_admin and user_id and users_choices_ref:
            self.self_ref = users_choices_ref.child(user_id)
            data = self.self_ref.get() or {}  # Safe default if no data
            self.cities = list(data.get("cities", []))
            self.choices = dict(data.get("choices", {}))

            if self.choices:
                self.set_stores(list(self.choices.keys()))

    def get_all_cities(self):
        return getCities()
    
    def set_cities(self, cities):
        self.cities = cities
        users_choices_ref.child(self.user_id).child("cities").set(cities)
        self.self_ref = users_choices_ref.child(self.user_id)

    def get_cities(self):
        return self.cities

    def get_all_stores(self):
        return list(STORE_CONFIG.keys())
    
    def set_stores(self, stores):
        self.handlers = {}

        for store_name in stores:
            if "extra_pages" in STORE_CONFIG[store_name] and "extra_vars" in STORE_CONFIG[store_name]:
                self.handlers[store_name] = STORE_CONFIG[store_name]["class"](
                    _main_page = STORE_CONFIG[store_name]["main_page"],
                    _extra_pages = STORE_CONFIG[store_name]["extra_pages"],
                    _extra_vars = STORE_CONFIG[store_name]["extra_vars"]
                )
            elif "extra_pages" in STORE_CONFIG[store_name]:
                self.handlers[store_name] = STORE_CONFIG[store_name]["class"](
                    _site_url = STORE_CONFIG[store_name]["base"], 
                    _main_page = STORE_CONFIG[store_name]["main_page"],
                    _extra_pages = STORE_CONFIG[store_name]["extra_pages"],
                )
            else:
                self.handlers[store_name] = STORE_CONFIG[store_name]["class"](
                    _site_url = STORE_CONFIG[store_name]["base"], 
                    _main_page = STORE_CONFIG[store_name]["main_page"],
                    _extra_vars = STORE_CONFIG[store_name]["extra_vars"],
                )

    def get_stores(self):
        return list(self.handlers.keys())

    def get_all_branches(self):
        if self.handlers == {}:
            raise RuntimeError("You need to set the stores first")
        
        stores_branches = {}

        for store_name in self.handlers:
            stores_branches[store_name] = self.handlers[store_name].get_branches(self.cities)
            
        return stores_branches

    def set_branches(self, choices, msg_bar_handler):
        global bars

        self.choices = choices
        main_bar = tqdm(
            total=len(self.choices),
            desc="Setting Stores",
            position=0,
            leave=False,
            dynamic_ncols=True,
            bar_format=MAIN_BAR_FORMAT
        )
        pos = 1
        bars = {}

        branches_to_add = []

        for store_name in self.choices:
            bars[store_name] = tqdm(
                total=len(self.choices[store_name]),
                desc=store_name,
                position=pos,
                leave=False,
                dynamic_ncols=True,
                bar_format=STORE_BAR_FORMAT
            )
            pos += 1

            # Determine missing branches
            missing_branches = [
                b for b in self.choices[store_name]
                if not update_db.if_branch_exists(store_name, b)
            ]

            # Populate handler's branches for missing ones
            if missing_branches and hasattr(self.handlers[store_name], "set_branches"):
                self.handlers[store_name].set_branches(missing_branches, msg_bar_handler=msg_bar_handler)

            for branch_name in self.choices[store_name]:
                if branch_name in missing_branches:
                    try:
                        update_db.add_branch(store_name, branch_name, self.handlers[store_name])
                        branches_to_add.append((store_name, branch_name))
                    except Exception as e:
                        msg_bar_handler.add_msg(f"Failed to add branch {branch_name}: {e}")

                bars[store_name].update(1)

            main_bar.update(1)

        msg_bar_handler.add_msg("Finished all stores")

        for bar in bars.values():
            bar.close()

        bars = {}
        main_bar.close()

        if not self.is_admin:
            self.self_ref.child("choices").set(choices)

    def set_branches_single_store(self, store_name, msg_bar_handler, branches_to_add):
        self.handlers[store_name].set_branches(self.choices[store_name], msg_bar_handler=msg_bar_handler)

        for branch_name in self.choices[store_name]:
            if not update_db.if_branch_exists(store_name, branch_name):
                if update_db.add_branch(store_name, branch_name, self.handlers[store_name]):
                    branches_to_add.append((store_name, branch_name))
                else:
                    msg_bar_handler.add_msg("Invalid file for branch: " + branch_name)

            bars[store_name].update(1)

    def get_branches(self):
        return self.choices
    
    def get_item_name(self, item_code):
        return items_code_name_ref.child(str(item_code)).get()

    def get_item_code(self, item_name):
        return str(items_name_code_ref.child(item_name).get())
    
    def get_item_prices_by_code(self, item_code, all=False):
        all_prices = items_stores_ref.child(item_code).get()

        if all:
            return all_prices

        prices = {}

        for store_name in all_prices:
            if store_name in self.choices:
                for branch_name in self.choices[store_name]:
                    if branch_name in all_prices[store_name]:
                        if store_name not in prices:
                            prices[store_name] = {}
                        
                        prices[store_name][branch_name] = all_prices[store_name][branch_name]

        return prices

    def get_item_prices_by_name(self, item_name, all=False):
        return self.get_item_prices_by_code(self.get_item_code(item_name), all)
    
    def get_all_items(self):
        all_items = {}

        for store_name, branches in self.choices.items():
            for branch_name in branches:
                branch_items = stores_items_ref.child(store_name).child(branch_name).get() or {}

                for item_code, item_price in branch_items.items():
                    if item_code not in all_items:
                        all_items[item_code] = {}
                    
                    if store_name not in all_items[item_code]:
                        all_items[item_code][store_name] = {}

                    all_items[item_code][store_name][branch_name] = item_price

        return all_items
    
    def get_items_code_name(self, codes):
        items_code_names = {}

        if codes:
            items_snapshot = items_code_name_ref.get() or {}
            
            for code in codes:
                items_code_names[code] = items_snapshot.get(str(code))

        return items_code_names
    
    def get_choices(self):
        return self.choices