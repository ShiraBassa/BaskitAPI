import requests
from generalRequestsFns import get_branches, update_url, sanitize_key


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
            name_clean = sanitize_key(name_clean)

            if "חסום" not in name_clean and "הכל" not in name_clean:
                all_branches[name_clean] = int(store["Kod"])

        return all_branches
    
    def get_branches(self, cities):
        return get_branches(self, cities)
    
    def set_branches(self, branches, fileType=4, date="", msg_bar_handler=None):
        self.branches = {}

        for branch in branches:
            if not self.set_branch_single(branch, fileType, date) and msg_bar_handler:
                msg_bar_handler.add_msg("Invalid file for branch " + branch)

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
        store_dict = response.json()
        
        if not store_dict:
            return False
        else:
            store_dict = store_dict[0]
            
        row_dict = {
            "date": store_dict["DateFile"],
            "type": fileType,
            "filename": store_dict["FileNm"],
            "code": self.all_branches[branch_name]
        }
        row_dict["url"] = self.site_url + "/Download/" + row_dict["filename"]
        self.branches[branch_name] = row_dict

        return True

    def update_url(self, branch_name):
        return update_url(self, branch_name)