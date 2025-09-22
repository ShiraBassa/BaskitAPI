import requests
from data_sets import getAbbr
from bs4 import BeautifulSoup
import certifi
import xml.etree.ElementTree as ET
from enum import Enum

class FileType(Enum):
        PRICE = "price"
        PRICE_FULL = "PriceFull"
        PROMO_FULL = "PromoFull"
        STORES = "Stores"

        DEFAULT = PRICE_FULL

class BranchesMap(Enum):
    STORE_ID = 0
    STORE_NAME = 3
    ADDRESS = 4
    CITY = 5
    ZIP_CODE = 6

class RequestsClassThree():
    def __init__(self, _main_page, _extra_pages, _extra_vars):
        self.all_urls = {}
        self.site_url = "https://url.publishedprices.co.il"
        self.main_page = _main_page
        self.extra_pages = _extra_pages
        
        if isinstance(_extra_vars, dict):
            self.username, self.password = _extra_vars.values()
        else:
            self.username = _extra_vars
            self.password = ""

        self.all_store_names = {}
        self.store_options = []
        self.final_choice = {}

        self.session = requests.Session()
        self.login()
        self.set_all_store_names()

    def getUrl(self, page_name):
        return self.site_url + page_name

    def login(self):
        resp = self.session.get(self.getUrl(self.extra_pages["login_base"]), verify=certifi.where(), allow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")

        csrf_tag = soup.find("meta", {"name": "csrftoken"})
        
        if not csrf_tag:
            raise Exception("CSRF token not found. Check login URL or session.")
        
        csrf_token = csrf_tag["content"]
        
        login_data = {
            "username": self.username,
            "password": self.password,
            "r": "",
            "csrftoken": csrf_token
        }

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        login_resp = self.session.post(self.getUrl(self.extra_pages["login_post"]), data=login_data, headers=headers, verify=certifi.where())
        
        if "Sign In" in login_resp.text or "Not currently logged in" in login_resp.text:
            raise Exception("Login failed, check credentials or CSRF token")

    def set_all_store_names(self):
        store_names_file = self.search_and_fetch(FileType.STORES.value)[0]
        store_names_file = self.getUrl(self.extra_pages["download"]) + store_names_file["fname"]

        resp = self.session.get(store_names_file, verify=certifi.where())
        content_type = resp.headers.get("Content-Type", "")

        if "xml" not in content_type.lower():
            print("Warning: Received content is not XML. Check URL or authentication.")
        else:
            try:
                root = ET.fromstring(resp.content)

                for store in root.findall(".//Store"):
                    self.all_store_names[store[BranchesMap.STORE_NAME.value].text] = int(store[BranchesMap.STORE_ID.value].text)
            
            except ET.ParseError as e:
                print("XML Parse Error:", e)

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

    def set_store_option_single(self, store_name, fileType=FileType.DEFAULT.value, date=""):
        storeId = self.all_store_names[store_name]
        files = self.search_and_fetch(str(storeId))
        
        for file in files:
            filename = file["fname"]

            if filename.startswith(fileType):
                row_dict = {
                    "url": self.getUrl(self.extra_pages["download"]) + filename,
                    "date": file["time"],
                    "type": fileType,
                    "filename": filename,
                    "code": int(filename.split("-")[1])
                }

                break
        
        print(row_dict)

    def set_store_options(self, options, fileType=FileType.DEFAULT.value, date=""):
        for store_name in options:
            self.set_store_option_single(store_name, fileType, date)

        return self.store_options
    
    def update_url(self, store_name):
        self.set_store_option_single(store_name, self.store_options["type"])

    def search_and_fetch(self, search):
        # Step 3: GET /file page first to get updated CSRF token for file actions
        file_page_resp = self.session.get(self.getUrl(self.main_page), headers={"User-Agent": "Mozilla/5.0"}, verify=certifi.where())
        soup_file = BeautifulSoup(file_page_resp.text, "html.parser")
        csrf_tag_file = soup_file.find("meta", {"name": "csrftoken"})
        if not csrf_tag_file:
            raise Exception("CSRF token not found on file page")
        csrf_token_file = csrf_tag_file["content"]

        # Step 4: POST to fetch directory listing
        payload = {
            "sEcho": 1,
            "iColumns": 6,
            "sColumns": "",
            "iDisplayStart": 0,
            "iDisplayLength": 2000,
            "mDataProp_0": "fname",
            "mDataProp_1": "ftime",
            "mDataProp_2": "size",
            "mDataProp_3": "typeLabel",
            "mDataProp_4": "ftime_sort",
            "mDataProp_5": "size_sort",
            "sSearch": search,
            "bRegex": False,
            "sSearch_0": "",
            "bRegex_0": False,
            "bSearchable_0": True,
            "sSearch_1": "",
            "bRegex_1": False,
            "bSearchable_1": True,
            "sSearch_2": "",
            "bRegex_2": False,
            "bSearchable_2": True,
            "sSearch_3": "",
            "bRegex_3": False,
            "bSearchable_3": True,
            "sSearch_4": "",
            "bRegex_4": False,
            "bSearchable_4": True,
            "sSearch_5": "",
            "bRegex_5": False,
            "bSearchable_5": True,
            "iSortingCols": 1,
            "iSortCol_0": 0,
            "sSortDir_0": "asc",
            "bSortable_0": True,
            "bSortable_1": True,
            "bSortable_2": True,
            "bSortable_3": True,
            "bSortable_4": True,
            "bSortable_5": True,
            "curDir": "/",
            "all_files": True,
            "csrftoken": csrf_token_file  # include in POST data
        }

        files_resp = self.session.post(
            self.getUrl(self.extra_pages["dir"]),
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-CSRF-Token": csrf_token_file,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
            },
            verify=certifi.where()
        )

        files = files_resp.json()

        return files["aaData"]