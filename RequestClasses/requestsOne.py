import requests
from bs4 import BeautifulSoup
from RequestClasses.generalRequestsFns import get_branches, update_url, sanitize_key


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
        self.branches_dropdown_id, self.default_pop_item = _extra_vars.values()
        self.branches = {}

        self.session = requests.Session()
        self.all_branches = self.get_all_branches()

    def get_url(self, catID=2, storeId=0, sort="Time", sortdir="ASC"):
        return  self.site_url + self.main_page + \
                "catID=" + str(catID) + \
                "&storeId=" + str(storeId) + \
                "&sort=" + sort + \
                "&sortdir=" + sortdir
    
    def get_all_branches(self):
        response = self.session.get(self.site_url)
        
        if response.status_code != 200:
            raise Exception("Failed to fetch page")
        
        soup = BeautifulSoup(response.text, "html.parser")
        select = soup.find("select", {"id": self.branches_dropdown_id})  # adjust ID if needed

        if not select:
            select = soup.find("select", {"name": self.branches_dropdown_id})  # fallback
        
        if not select:
            raise Exception("Store dropdown not found on the page")

        options = select.find_all("option")
        options = {option.text.strip(): option["value"] for option in options}
        options.pop(self.default_pop_item)
        all_branches = {}

        for full_name, code in options.items():
            clean_name = full_name.split(' - ', 1)[1] if ' - ' in full_name else full_name
            clean_name = sanitize_key(clean_name)
            all_branches[clean_name.strip()] = int(code)

        return all_branches
    
    def get_branches(self, cities):
        return get_branches(self, cities)

    def set_branches(self, branches, catID=2, sort="Time", sortdir="ASC", msg_bar_handler=None):
        self.branches = {}

        for branch in branches:
            if not self.set_branch_single(branch, catID, sort, sortdir) and msg_bar_handler:
                msg_bar_handler.add_msg("Invalid file for branch " + branch)

        return self.branches
    
    def set_branch_single(self, branch_name, catID=2, sort="Time", sortdir="ASC"):
        storeId = self.all_branches[branch_name]
        response = requests.get(self.get_url(catID, storeId, sort, sortdir))
        
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
            "code": self.all_branches[branch_name]
        }

        self.branches[branch_name] = row_dict
        
        return True
    
    def update_url(self, branch_name):
        return update_url(self, branch_name)