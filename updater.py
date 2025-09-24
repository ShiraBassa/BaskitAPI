from supermarketsHandler import mainRequestsHandler
from data_sets import *
from update_db import update_all_stores
from msgBarHandler import msg_bar
from time import sleep


def get_all_existing_stores():
    stores_branches = {}
    stores_urls = stores_urls_ref.get()

    for store_name in stores_urls:
        stores_branches[store_name] = []
        
        for branch_name in stores_urls[store_name]:
            stores_branches[store_name].append(branch_name)

    return stores_branches


def main():
    handler = mainRequestsHandler()
    stores_branches = get_all_existing_stores()

    print("\033c", end="")
    msg_bar_handler = msg_bar(len(stores_branches) + 2)
    handler.set_stores(list(stores_branches.keys()))
    handler.set_branches(stores_branches, msg_bar_handler)
    update_all_stores(handler.handlers)
    
    msg_bar_handler.close()

if __name__ == "__main__":
    main()