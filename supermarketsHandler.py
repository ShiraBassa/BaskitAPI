from requestsOne import RequestsClassOne
from requestsTwo import RequestsClassTwo
from requestsThree import RequestsClassThree
from enum import Enum
import data_sets
import update_db
from tqdm import tqdm
import threading
from time import sleep
from msgBarHandler import msg_bar


SHUFERSAL = "shufersal"
KING_STORE = "kingstore"
SHUK_HAYIR = "shuk_hayir"
MAAYAN_2000 = "maayan2000"
GOOD_PHARM = "goodpharm"
ZOL_VEBEGADOL = "zolvebegadol"
SUPER_SAPIR = "supersapir"
CITY_MARKET = "citymarket"
SUPER_BAREKET = "superbareket"
KT_SHIVUK = "ktshivuk"
SHEFA_BIRKAT_HASHEM = "shefa_birkat_hashem"
CARREFOUR = "carrefour"
DOR_ALON = "dor_alon"
TIV_TAAM = "tiv_taam"
YOHANANOF = "yohananof"
OSHER_AD = "osher_ad"
SALAH_DABAH = "salah_dabah"
STOP_MARKET = "stop_market"
POLITZER = "politzer"
YELLOW = "yellow"
SUPER_YUDA = "super_yuda"
FRESHMARKET = "freshmarket"
KESHET_TEAMIM = "keshet_keamim"
RAMI_LEVI = "rami_levi"
SUPER_COFIX = "super_cofix"


REQUESTS_CLASSES = [RequestsClassOne, RequestsClassTwo, RequestsClassThree]

STORE_CONFIG = {
    SHUFERSAL: {
        "class": REQUESTS_CLASSES[0],
        "base": "https://prices.shufersal.co.il",
        "main_page": "/FileObject/UpdateCategory?",
        "extra_vars": {
            "dropdown_id": "ddlStore",
            "default_item": "All"
        }
    },

    KING_STORE: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://kingstore.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SHUK_HAYIR: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://shuk-hayir.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    MAAYAN_2000: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://maayan2000.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    GOOD_PHARM: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://goodpharm.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    ZOL_VEBEGADOL: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://ZolVebegadol.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SUPER_SAPIR: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://supersapir.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    CITY_MARKET: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://citymarketkiryatgat.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SUPER_BAREKET: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://superbareket.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    KT_SHIVUK: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://ktshivuk.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SHEFA_BIRKAT_HASHEM: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://shefabirkathashem.binaprojects.com",
        "main_page": "/MainIO_Hok",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    CARREFOUR: {
        "class": REQUESTS_CLASSES[0],
        "base": "https://prices.carrefour.co.il",
        "main_page": "/FileObject/UpdateCategory?",
        "extra_vars": {
            "dropdown_id": "branch_filter",
            "default_item": "סניף"
        }
    },

    DOR_ALON: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "doralon"
    },

    TIV_TAAM: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "TivTaam"
    },

    YOHANANOF: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "yohananof"
    },

    OSHER_AD: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "osherad"
    },

    SALAH_DABAH: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": {
            "username": "SalachD",
            "password": "12345"
        }
    },

    STOP_MARKET: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "Stop_Market"
    },

    POLITZER: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "politzer"
    },

    YELLOW: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": {
            "username": "Paz_bo",
            "password": "paz468"
        }
    },

    FRESHMARKET: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "freshmarket"
    },

    KESHET_TEAMIM: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "Keshet"
    },

    RAMI_LEVI: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "RamiLevi"
    },

    SUPER_COFIX: {
        "class": REQUESTS_CLASSES[2],
        "main_page": "/file",
        "extra_pages": {
            "login_base": "/login",
            "login_post": "/login/user",
            "dir": "/file/json/dir",
            "download": "/file/d/"
        },
        "extra_vars": "SuperCofixApp"
    }
}


class mainRequestsHandler():
    def __init__(self):
        self.cities = []
        self.handlers = {}
        self.choices = {}

    def get_all_cities(self):
        return data_sets.getCities()
    
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