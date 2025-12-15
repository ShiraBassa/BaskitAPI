import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from RequestClasses.requestsOne import RequestsClassOne
from RequestClasses.requestsTwo import RequestsClassTwo
from RequestClasses.requestsThree import RequestsClassThree
import firebase_admin
from firebase_admin import credentials, db

REQUESTS_CLASSES = [RequestsClassOne, RequestsClassTwo, RequestsClassThree]


SHUFERSAL = "שופרסל"
KING_STORE = "קינג סטור"
SHUK_HAYIR = "שוק העיר"
MAAYAN_2000 = "מעיין אלפיים"
GOOD_PHARM = "גוד פארם"
ZOL_VEBEGADOL = "זול ובגדול"
SUPER_SAPIR = "סופר ספיר"
CITY_MARKET = "סיטי מרקט"
SUPER_BAREKET = "סופר ברקת"
KT_SHIVUK = "קיי.טי. שיווק"
SHEFA_BIRKAT_HASHEM = "שפע ברכת השם"
CARREFOUR = "קרפור"
DOR_ALON = "דור אלון"
TIV_TAAM = "טיב טעם"
YOHANANOF = "יוחננוף"
OSHER_AD = "אושר עד"
SALAH_DABAH = "סלאח דבאח"
STOP_MARKET = "סטופ מרקט"
POLITZER = "פוליצר"
YELLOW = "יילו"
SUPER_YUDA = "סופר יודה"
FRESH_MARKET = "פרשמרקט"
KESHET_TEAMIM = "קשת טעמים"
RAMI_LEVI = "רמי לוי"
SUPER_COFIX = "סופר קופיקס"


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

    #ZOL_VEBEGADOL: {
    #    "class": REQUESTS_CLASSES[1],
    #    "base": "https://ZolVebegadol.binaprojects.com",
    #    "main_page": "/MainIO_Hok",
    #    "extra_pages": {
    #        "stores": "/Select_Store"
    #    }
    #},

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

    # CARREFOUR: {
    #     "class": REQUESTS_CLASSES[0],
    #     "base": "https://prices.carrefour.co.il",
    #     "main_page": "/FileObject/UpdateCategory?",
    #     "extra_vars": {
    #         "dropdown_id": "branch_filter",
    #         "default_item": "סניף"
    #     }
    # }
}

MAIN_BAR_FORMAT = "{desc} {percentage:3.0f}% | {bar} | {n_fmt}/{total_fmt}"
STORE_BAR_FORMAT = "    {desc} {percentage:3.0f}% | {bar} | {n_fmt}/{total_fmt}"
MSG_BAR_FORMAT = "{desc}"

cred_api = credentials.Certificate("Data/baskit_api_key.json")
app_api = firebase_admin.initialize_app(cred_api, {
    'databaseURL': 'https://baskitapi-default-rtdb.firebaseio.com/'
}, name="baskit_api_app")

cred_baskit = credentials.Certificate("Data/baskit_key.json")
app_baskit = firebase_admin.initialize_app(cred_baskit, {
    'databaseURL': 'https://baskit-b6600-default-rtdb.firebaseio.com/'
}, name="baskit_app")
    
stores_items_ref = db.reference('Stores-Items', app=app_api)
items_stores_ref = db.reference('Items-Stores', app=app_api)
stores_urls_ref = db.reference('Stores-Urls', app=app_api)
items_code_name_ref = db.reference('Items_Code-Name', app=app_api)
items_name_code_ref = db.reference('Items_Name-Code', app=app_api)
users_choices_ref = db.reference('Users-Choices', app=app_api)