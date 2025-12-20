import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Classes.userHandler import User
from Data.data_sets import *
from Data.update_db import update_all_stores, clear_all
from Classes.msgBarHandler import msg_bar


def get_all_existing_stores():
    stores_branches = {}
    stores_urls = stores_urls_ref.get()

    for store_name in stores_urls:
        stores_branches[store_name] = []
        
        for branch_name in stores_urls[store_name]:
            stores_branches[store_name].append(branch_name)

    return stores_branches

def main():
    handler = User(is_admin=True)
    stores_branches = get_all_existing_stores()

    clear_all()
    print("\033c", end="")
    msg_bar_handler = msg_bar(len(stores_branches) + 2)
    handler.set_stores(list(stores_branches.keys()))
    handler.set_branches(stores_branches, msg_bar_handler=msg_bar_handler)
    update_all_stores(handler.handlers)
    
    msg_bar_handler.close()

if __name__ == "__main__":
    main()