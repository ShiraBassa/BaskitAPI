from flask import jsonify
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import re
from data_sets import getAbbr


class RequestsClassOne():
    catId_map = {
        "prices": 1,
        "pricefull": 2,
        "promos": 3,
        "promosfull": 4,
        "stores": 5
    }

    def __init__(self, _site_url, _main_page, _extra_vars):
        self.all_urls = {}
        self.site_url = _site_url
        self.main_page = _main_page
        self.stores_dropdown_id, self.default_pop_item = _extra_vars.values()
        self.all_store_names = {}
        self.store_options = []
        self.final_choice = {}

        self.session = requests.Session()
        self.set_all_store_names()

    def getUrl(self, catID=2, storeId=0, sort="Time", sortdir="ASC"):
        return  self.site_url + self.main_page + \
                "catID=" + str(catID) + \
                "&storeId=" + str(storeId) + \
                "&sort=" + sort + \
                "&sortdir=" + sortdir
    
    def set_all_store_names(self):
        response = self.session.get(self.site_url)
        
        if response.status_code != 200:
            raise Exception("Failed to fetch page")
        
        soup = BeautifulSoup(response.text, "html.parser")
        select = soup.find("select", {"id": self.stores_dropdown_id})  # adjust ID if needed

        if not select:
            select = soup.find("select", {"name": self.stores_dropdown_id})  # fallback
        
        if not select:
            raise Exception("Store dropdown not found on the page")

        options = select.find_all("option")
        options = {option.text.strip(): option["value"] for option in options}
        options.pop(self.default_pop_item)
        self.all_store_names = {}

        for full_name, code in options.items():
            # Remove leading "<number> - " from the key
            clean_name = full_name.split(' - ', 1)[1] if ' - ' in full_name else full_name
            self.all_store_names[clean_name.strip()] = int(code)

    def get_store_names(self, cities):
        self.store_options = []

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
                self.store_options.append(store_name)
            
        return self.store_options

    def set_store_option_single(self, store_name, catID=2, storeId=0, sort="Time", sortdir="ASC"):
        response = requests.get(self.getUrl(catID, storeId, sort, sortdir))
        
        if response.status_code != 200:
            return False
        
        soup = BeautifulSoup(response.text, "html.parser")
        tr = soup.find_all("tr")[1]
        tds = tr.find_all("td")

        if len(tds) != 8:
            return False
        
        a_tag = tds[0].find("a")
        if not a_tag:
            return False
        
        row_dict = {
            "url": a_tag['href'],
            "date": tds[1].get_text(strip=True),
            "type": catID,
            "filename": tds[6].get_text(strip=True),
            "code": self.all_store_names[store_name]
        }

        self.final_choice[store_name] = row_dict

    def set_branch_choices(self, options, catID=2, sort="Time", sortdir="ASC"):
        self.final_choice = {}

        for store_name in options:
            self.set_store_option_single(store_name, catID, self.all_store_names[store_name], sort, sortdir)

        return self.final_choice
    
    def update_url(self, store_name):
        self.set_store_option_single(store_name, self.store_options["type"])