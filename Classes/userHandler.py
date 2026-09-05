from Data.update_db import *
from RequestClasses.generalRequestsFns import getCities
import Data.update_db as update_db
from concurrent.futures import ThreadPoolExecutor
import time

executor = ThreadPoolExecutor(max_workers=12)

bars = {}


def get_embedded_category(item_code):
    item_info = items_info_ref.child(str(item_code)).get() or {}

    if isinstance(item_info, dict):
        category = item_info.get("category")

        if category:
            return str(category)

    return None


class User():
    shared_empty_branches_cache = set()
    shared_empty_branches_in_progress = set()
    def __init__(self, user_id=None, is_admin=False):
        self.user_id = user_id
        self.is_admin = is_admin
        self.cities = []
        self.choices = {}
        self.handlers = {}

        self.items_cache = None
        self.items_cache_ts = 0
        self.cache_ttl = 10

        self.empty_branches_cache = User.shared_empty_branches_cache
        self.empty_branches_in_progress = User.shared_empty_branches_in_progress

        if not is_admin and user_id and users_choices_ref:
            self.self_ref = users_choices_ref.child(user_id)
            data = self.self_ref.get() or {}

            cities_data = data.get("cities", [])
            
            if isinstance(cities_data, dict):
                self.cities = [c for c in cities_data.values() if c is not None]
            else:
                self.cities = [c for c in cities_data if c is not None]
                
            self.choices = dict(data.get("choices", {}))

    def get_all_cities(self):
        return getCities()
    
    def set_cities(self, cities):
        cities = [c for c in cities if c is not None]
        self.cities = cities
        users_choices_ref.child(self.user_id).child("cities").set(cities)
        self.self_ref = users_choices_ref.child(self.user_id)

    def get_cities(self):
        return self.cities

    def get_all_stores(self):
        return list(STORE_CONFIG.keys())

    def get_stores(self):
        return list(self.handlers.keys())

    def get_all_branches(self):
        if self.handlers == {}:
            return {}
        
        stores_branches = {}

        for store_name in self.handlers:
            branches = self.handlers[store_name].get_branches(self.cities)
            
            if branches:
                stores_branches[store_name] = branches
            
        return stores_branches

    def set_branches(self, choices):
        cleaned_choices = {
            store: [b for b in branches if b is not None]
            for store, branches in choices.items()
            if branches
        }

        self.choices = cleaned_choices
        self.items_cache = None
        self.items_cache_ts = 0

        def _warm(u):
            try:
                u.get_all_items()
            except Exception as e:
                print("Warmup failed:", e)

        if cleaned_choices:
            executor.submit(_warm, self)

        if not self.is_admin and hasattr(self, "self_ref"):
            self.self_ref.child("choices").set(cleaned_choices)

    def get_branches(self):
        return self.choices
    
    def get_item_prices_by_code(self, item_code, all=False):
        all_prices = items_stores_ref.child(item_code).get()

        if not all_prices or not isinstance(all_prices, dict):
            return {}

        if all:
            return {
                store: {branch: price for branch, price in branches.items() if price is not None}
                for store, branches in all_prices.items()
                if isinstance(branches, dict)
            }
    
        prices = {}

        for store_name in all_prices:
            if store_name in self.choices:
                for branch_name in self.choices[store_name]:
                    price = all_prices[store_name].get(branch_name)
                    if price is not None:
                        prices.setdefault(store_name, {})[branch_name] = price
        
        return prices
    
    def get_all_items(self):
        now = time.time()

        if self.items_cache is not None and (now - self.items_cache_ts) < self.cache_ttl:
            return self.items_cache

        all_items = {}
        empty_branches = []
        start_time = time.time()
        MAX_TOTAL_TIME = 3

        if not self.choices:
            self.items_cache = all_items
            self.items_cache_ts = now
            return all_items

        # concurrent fetch with limited workers to avoid blocking
        def fetch_branch(store_name, branch_name):
            ref = stores_items_ref.child(store_name).child(branch_name)
            try:
                try:
                    data = ref.get(timeout=2) or {}
                except TypeError:
                    # fallback if timeout not supported
                    data = ref.get() or {}
            except Exception as e:
                print(f"Firebase read failed {store_name}/{branch_name}: {e}")
                data = {}
            return store_name, branch_name, data

        futures = []
        MAX_BRANCHES = 10  # prevent overload on new users / new supermarkets

        for store_name, branches in self.choices.items():
            if not branches:
                continue

            for branch_name in branches[:MAX_BRANCHES]:
                futures.append(executor.submit(fetch_branch, store_name, branch_name))

        from concurrent.futures import as_completed

        for f in as_completed(futures, timeout=MAX_TOTAL_TIME):
            # global timeout safeguard
            if time.time() - start_time > MAX_TOTAL_TIME:
                print("Global timeout reached, stopping fetch early")
                break

            try:
                store_name, branch_name, branch_items = f.result(timeout=1)
            
            except Exception as e:
                print("Branch fetch failed or timed out:", e)
                continue

            if not isinstance(branch_items, dict):
                continue
            
            if not branch_items:
                key = f"{store_name}:{branch_name}"

                if key not in self.empty_branches_cache and key not in self.empty_branches_in_progress:
                    self.empty_branches_in_progress.add(key)
                    empty_branches.append((store_name, branch_name))

                continue

            for item_code, item_price in branch_items.items():
                if item_code is None:
                    continue

                code = str(item_code).strip()
                if not code or code.lower() == "null":
                    continue

                if item_price is None or item_price <= 0:
                    continue

                all_items.setdefault(code, {}).setdefault(store_name, {})[branch_name] = item_price

        def fill_empty():
            try:
                for store_name, branch_name in empty_branches:
                    key = f"{store_name}:{branch_name}"
                    
                    try:
                        if update_db.if_branch_exists(store_name, branch_name):
                            self.empty_branches_cache.add(key)
                            continue

                        if store_name not in STORE_CONFIG:
                            continue

                        store_class = STORE_CONFIG[store_name]["class"]

                        handler = None
                        try:
                            config = STORE_CONFIG[store_name]

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
                        except Exception as e:
                            print(f"Failed creating handler for {store_name}: {e}")
                            continue

                        if not handler or not handler.all_branches:
                            continue

                        handler.set_branch_single(branch_name)
                        update_db.add_branch(store_name, branch_name, handler)
                        self.empty_branches_cache.add(key)

                    except Exception as e:
                        print(f"Failed filling branch {store_name}/{branch_name}: {e}")
                    
                    finally:
                        self.empty_branches_in_progress.discard(key)
            
            except Exception as e:
                print("Failed filling empty branches:", e)

        if empty_branches:
            executor.submit(fill_empty)

        # cache result
        self.items_cache = all_items
        self.items_cache_ts = now

        return all_items
    
    def get_item_infos(self, item_codes=None):
        if not item_codes:
            item_codes = list(self.get_all_items().keys())

        available_items = set(item_codes)
        result = {}

        items_snapshot = items_info_ref.get() or {}

        for code in item_codes:
            str_code = str(code)

            if str_code in available_items:
                info = items_snapshot.get(str_code)
                if info:
                    result[str_code] = info

        return result

    def get_item_info(self, item_code):
        if not item_code:
            return None

        available_items = set(self.get_all_items().keys())
        str_code = str(item_code)

        if str_code not in available_items:
            return None

        items_snapshot = items_info_ref.get() or {}
        return items_snapshot.get(str_code)

    def get_groups(self):
        user_items = set(self.get_all_items().keys())
        if not user_items:
            return {}

        groups_snapshot = groups_ref.get() or {}
        result = {}

        for base_name, codes in groups_snapshot.items():
            if not isinstance(codes, list):
                continue

            filtered_codes = [code for code in codes if str(code) in user_items]

            if filtered_codes:
                result[base_name] = filtered_codes

        return result
    
    def get_choices(self):
        return self.choices
    
    def get_item_category_by_code(self, code):
        category = get_embedded_category(code)

        if category:
            return category

        legacy_category = items_categories_ref.child(str(code)).get()

        if legacy_category:
            try:
                items_info_ref.child(str(code)).child("category").set(
                    str(legacy_category)
                )
            except Exception as e:
                print(f"Failed syncing legacy category for {code}: {e}")

            return str(legacy_category)

        # run Gemini classification in background so request is not blocked
        def classify_task(c):
            try:
                ai = AIHandler([c])
                ai.run_async()
            except Exception as e:
                print(f"Background classification failed for {c}: {e}")

        executor.submit(classify_task, code)
        return None

    def get_group(self, name):
        if not name:
            return None

        group = groups_ref.child(name).get()

        if isinstance(group, list):
            return [str(c) for c in group]
        
        return None

    def get_item_category_by_name(self, name):
        group = self.get_group(name)

        if not group:
            return None

        for code in group:
            category = self.get_item_category_by_code(code)

            if category:
                return str(category)

        return self.get_item_category_by_code(group[0])

    def get_items_categories(self):
        items = list(self.get_all_items().keys())

        if not items:
            return {}

        items_snapshot = items_info_ref.get() or {}
        legacy_categories = items_categories_ref.get() or {}

        legacy_categories = {
            str(k): v for k, v in legacy_categories.items()
        }

        categories = {}

        for item_code in items:
            str_code = str(item_code)
            item_info = items_snapshot.get(str_code) or {}

            if not isinstance(item_info, dict):
                continue

            category = item_info.get("category")

            if category:
                categories[str_code] = category
                continue

            legacy_category = legacy_categories.get(str_code)

            if legacy_category:
                categories[str_code] = legacy_category

        return categories