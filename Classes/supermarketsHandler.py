from Data.data_sets import *
from RequestClasses.generalRequestsFns import getCities
import Data.update_db as update_db
from tqdm import tqdm
from time import sleep
from Classes.msgBarHandler import msg_bar
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
import traceback


bars = {}

class mainRequestsHandler():
    def __init__(self):
        self.cities = []
        self.handlers = {}
        self.choices = {}

    def get_all_cities(self):
        return getCities()
    
    def set_cities(self, cities):
        self.cities = cities

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

        with ThreadPoolExecutor() as executor:
            futures = []

            for store_name in self.choices:
                bars[store_name] = tqdm(
                    total=len(self.choices[store_name]), 
                    desc=store_name, 
                    position=pos, 
                    leave=False, 
                    dynamic_ncols=True, 
                    bar_format=STORE_BAR_FORMAT
                    )
                futures.append(
                    executor.submit(self.set_branches_single_store, store_name, msg_bar_handler)
                )
                pos += 1

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Branch update generated an exception: {exc}")
                    traceback.print_exc()  # full stack trace
                finally:
                    # Refresh the bar for each finished branch
                    main_bar.update(1)
        
        msg_bar_handler.add_msg("Finished all stores")

        for bar in bars.values():
            bar.close()

        bars = {}
        main_bar.close()

    def set_branches_single_store(self, store_name, msg_bar_handler):
        self.handlers[store_name].set_branches(self.choices[store_name], msg_bar_handler=msg_bar_handler)
    
        for branch_name in self.choices[store_name]:
            if not update_db.if_branch_exists(store_name, branch_name):
                if not update_db.add_branch(
                    store_name,
                    branch_name,
                    self.handlers[store_name]
                ):
                    msg_bar_handler.add_msg("Invalid file for branch: " + branch_name)

            bars[store_name].update(1)
        
    def get_branches(self):
        return self.choices
    
    def get_item_prices_by_code(self, item_code):
        return items_stores_ref.child(item_code).get()

    def get_item_prices_by_name(self, item_name):
        return items_stores_ref.child(self.get_item_code(item_name)).get()

    def get_item_name(self, item_code):
        return items_code_name_ref.child(str(item_code)).get()

    def get_item_code(self, item_name):
        return str(items_name_code_ref.child(item_name).get())


def main_test():
    #update_db.remove_all()
    handler = mainRequestsHandler()
    cities = handler.get_all_cities()
    print(cities)
    handler.set_cities(cities)

    stores = handler.get_all_stores()
    print(stores)
    check_stores = stores
    handler.set_stores(check_stores)

    stores_branches = handler.get_all_branches()
    print(stores_branches)
    choices = {}

    for store in check_stores:
        if stores_branches[store]:
            choices[store] = [stores_branches[store][0]]
        else:
            print("/////////", store, handler.handlers[store].all_branches, "////")
            sleep(100)
        
    print(choices)
    #sleep(100)
    print("\033c", end="")
    msg_bar_handler = msg_bar(len(choices) + 2)
    handler.set_branches(choices, msg_bar_handler)
    msg_bar_handler.close()

if __name__ == "__main__":
    main_test()