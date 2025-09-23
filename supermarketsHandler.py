from data_sets import *
import update_db
from tqdm import tqdm
import threading
from time import sleep
from msgBarHandler import msg_bar


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

    def set_branches(self, choices):
        global msg_bar

        self.choices = choices

        # Create main progress bar (stores level)
        main_bar_lock = threading.Lock()
        main_bar = tqdm(total=len(self.choices), desc="Stores", position=0, leave=False, ncols=90)

        for store_name in self.choices:
            self.handlers[store_name].set_branches(self.choices[store_name])

            for branch_name in self.choices[store_name]:
                if not update_db.if_branch_exists(store_name, branch_name):
                    update_db.add_branch(
                        store_name,
                        branch_name,
                        self.handlers[store_name].branches[branch_name]["url"],
                        self.handlers[store_name],
                        global_bar_lock=main_bar_lock,
                        global_bar=main_bar
                    )

                    msg_bar_handler.add_msg(f"Finished branch: {branch_name}", True)

            msg_bar_handler.add_msg(f"Finished store: {store_name}")
    
        msg_bar_handler.close("Finished all stores")
        main_bar.close()
        
    def get_branches(self):
        return self.choices

    
def update_database(handler):
    update_db.update_all_stores(handler.handlers)

if __name__ == "__main__":
    #update_db.remove_all()
    handler = mainRequestsHandler()
    cities = handler.get_all_cities()
    print(cities)
    handler.set_cities(cities[0:6])

    stores = handler.get_all_stores()
    print(stores)
    check_stores = [stores[0], stores[5]]
    handler.set_stores(check_stores)

    stores_branches = handler.get_all_branches()
    print(stores_branches)
    choices = {}

    for store in check_stores:
        choices[store] = [stores_branches[store][0]]
        
    print(choices)
    #sleep(5)
    print("\033c", end="")
    msg_bar_handler = msg_bar()
    handler.set_branches(choices)
    #update_database(handler)