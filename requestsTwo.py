import requests
from data_sets import getAbbr


class RequestsClassTwo():
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
        self.branches = {}

        self.session = requests.Session()
        self.all_branches = self.get_all_branches()

    def get_url(self, page_name):
        return self.site_url + page_name + ".aspx"

    def get_all_branches(self):
        response = self.session.post(self.get_url(self.extra_pages["stores"]), data={})
        
        if response.status_code != 200:
            return "error"
        
        stores = response.json()
        all_branches = {}

        for store in stores:
            name = store["Nm"].strip()
            name_clean = " ".join(name.split()[1:]) if name[0].isdigit() else name
            all_branches[name_clean] = int(store["Kod"])

        return all_branches
    
    def get_branches(self, cities):
        branches = []

        for branch_name in self.all_branches:
            has_city = False

            for city in cities:
                if not has_city:
                    if city in branch_name:
                        has_city = True
                    else:
                        abbr = getAbbr(city)

                        if abbr and abbr in branch_name:
                            has_city = True

            if has_city:
                branches.append(branch_name)
            
        return branches
    
    def set_branches(self, branches, fileType=4, date=""):
        self.branches = {}

        for branch in branches:
            self.set_branch_single(branch, fileType, date)

        return self.branches

    def set_branch_single(self, branch_name, fileType=4, date=""):
        storeId = self.all_branches[branch_name]
            
        payload = {
            "WStore": storeId,
            "WDate": date,
            "WFileType": fileType
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0"
        }

        response = self.session.post(self.get_url(self.main_page), data=payload, headers=headers)
        
        try:
            store_dict = response.json()[0]
            row_dict = {
                "date": store_dict["DateFile"],
                "type": fileType,
                "filename": store_dict["FileNm"],
                "code": self.all_branches[branch_name]
            }
            row_dict["url"] = self.get_url(self.main_page) + "/Download/" + row_dict["filename"]

            self.branches[branch_name] = row_dict

        except ValueError:
            return False

    def update_url(self, branch_name):
        self.set_branch_single(branch_name, self.all_branches["type"])