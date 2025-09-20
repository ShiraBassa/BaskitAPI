import requests
from data_sets import getAbbr


class RequestsClassThree():
    fileType_map = {
        "stores": 1,
        "prices": 2,
        "promos": 3,
        "pricefull": 4,
        "promosfull": 5
    }

    def __init__(self, _site_url, _main_page, _extra_pages):
        self.all_urls = {}
        self.site_url = _site_url
        self.main_page = _main_page
        self.extra_pages = _extra_pages
        self.all_store_names = {}
        self.store_options = []
        self.final_choice = {}

        self.session = requests.Session()
        self.set_all_store_names()

    def getUrl(self, page_name):
        return self.site_url + page_name + ".aspx"

    def set_all_store_names(self):
        response = self.session.post(self.getUrl(self.extra_pages["stores"]), data={})
        
        if response.status_code != 200:
            return "error"
        
        stores = response.json()

        for store in stores:
            name = store["Nm"].strip()
            name_clean = " ".join(name.split()[1:]) if name[0].isdigit() else name
            self.all_store_names[name_clean] = int(store["Kod"])

    def get_store_names(self, cities):
        self.store_options = {}

        for store_name in self.all_store_names:
            has_city = False

            for city in cities:
                if not has_city:
                    if city in store_name:
                        has_city = True
                    else:
                        abbr = getAbbr(city)

                        if abbr and abbr in store_name:
                            has_city = True

            if has_city:
                self.store_options[store_name] = {}
            
        return list(self.store_options.keys())

    def set_store_option_single(self, store_name, fileType=4, date=""):
        storeId = self.all_store_names[store_name]
            
        payload = {
            "WStore": storeId,
            "WDate": date,
            "WFileType": fileType
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0"
        }

        response = self.session.post(self.getUrl(self.main_page), data=payload, headers=headers)
        
        try:
            store_dict = response.json()[0]
            row_dict = {
                "date": store_dict["DateFile"],
                "type": fileType,
                "filename": store_dict["FileNm"],
                "code": self.all_store_names[store_name]
            }
            row_dict["url"] = self.getUrl(self.main_page) + "/Download/" + row_dict["filename"]

            self.store_options[store_name] = row_dict
        except ValueError:
            return False

    def set_store_options(self, options, fileType=4, date=""):
        for store_name in options:
            self.set_store_option_single(store_name, fileType, date)

        return self.store_options
    
    def update_url(self, store_name):
        self.set_store_option_single(store_name, self.store_options["type"])


import requests
import certifi

# URLs
login_url = "https://url.publishedprices.co.il/login"
files_url = "https://url.publishedprices.co.il/file"

# Your credentials
payload = {
    "username": "TivTaam",
    "password": ""
}

session = requests.Session()
login_response = session.post(
    "https://url.publishedprices.co.il/login",
    data=payload,
    verify=certifi.where()  # use certifi’s CA bundle
)

if login_response.status_code == 200:
    print("Logged in successfully!")
else:
    print("Login failed:", login_response.status_code)

# Access the files page
files_response = session.get(files_url)
if files_response.status_code == 200:
    print("Files page content:")
    print(files_response.text)  # HTML content of the files page
else:
    print("Failed to load files page:", files_response.status_code)