from requestsOne import RequestsClassOne
from requestsTwo import RequestsClassTwo
from enum import Enum


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


REQUESTS_CLASSES = [RequestsClassOne, RequestsClassTwo]

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
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    MAAYAN_2000: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://maayan2000.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    GOOD_PHARM: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://goodpharm.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    ZOL_VEBEGADOL: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://zolvebegadol.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SUPER_SAPIR: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://supersapir.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    CITY_MARKET: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://citymarketkiryatgat.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SUPER_BAREKET: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://superbareket.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    KT_SHIVUK: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://ktshivuk.binaprojects.com",
        "main_page": "/Main.aspx",
        "extra_pages": {
            "stores": "/Select_Store"
        }
    },

    SHEFA_BIRKAT_HASHEM: {
        "class": REQUESTS_CLASSES[1],
        "base": "https://shefabirkathashem.binaprojects.com",
        "main_page": "/Main.aspx",
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
    }
}

class mainRequestsHandler():
    def __init__(self):
        self.store_options = {}
        self.handlers = {}

        for store_name in [CARREFOUR, KING_STORE]:
            if "extra_pages" in STORE_CONFIG[store_name]:
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

    def get_all_store_names(self, cities):
        for store_name in self.handlers:
            self.store_options[store_name] = self.handlers[store_name].get_store_names(cities)

        return self.store_options
    

if __name__ == "__main__":
    handler = mainRequestsHandler()
    print(handler.get_all_store_names(["תל אביב", "בית שמש"]))