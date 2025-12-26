import requests
import re
from bs4 import BeautifulSoup
from RequestClasses.generalRequestsFns import get_branches, update_url, sanitize_key


class RequestsClassFour():
    def __init__(self, _store_name, _site_url, _extra_vars):
        self.store_name = _store_name
        self.all_urls = {}
        self.site_url = _site_url
        self.branches_dropdown_id, self.default_pop_item = _extra_vars.values()
        self.branches = {}
        
        self.session = requests.Session()
        self.all_branches = self.get_all_branches(force_refresh=True)
        
        self.session_state = {
            "branch_filter": None
        }

    def get_all_branches(self, force_refresh=False):
        if not force_refresh:
            return dict(self.all_branches)
        
        self.all_branches = {}
        
        try:
            response = self.session.get(self.site_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            
            if response.status_code != 200:
                return dict(self.all_branches)

            soup = BeautifulSoup(response.text, "html.parser")
            select = soup.find("select", {"id": self.branches_dropdown_id})
            
            if not select:
                select = soup.find("select", {"name": self.branches_dropdown_id})
            
            if not select:
                return dict(self.all_branches)

            options = select.find_all("option")
            tmp = {}
            
            for option in options:
                text = (option.text or "").strip()
                val = option.get("value")
                if not text or val is None:
                    continue
                tmp[text] = val

            if self.default_pop_item:
                tmp.pop(self.default_pop_item, None)

            scraped = {}
            
            for full_name, code in tmp.items():
                clean_name = full_name.split(" - ", 1)[1] if " - " in full_name else full_name
                clean_key = sanitize_key(clean_name).strip()
                code_str = str(code).strip()
                if code_str.isdigit():
                    scraped[clean_key] = f"{int(code_str):04d}"

            for k, v in scraped.items():
                self.all_branches.setdefault(k, v)

        except Exception:
            return dict(self.all_branches)

        return dict(self.all_branches)

    def get_branches(self, cities):
        return get_branches(self, cities)

    def set_branches(self, branches, catID="PriceFull", sort="Time", sortdir="ASC", msg_bar_handler=None):
        self.branches = {}

        for branch in branches:
            if not self.set_branch_single(branch, catID, sort, sortdir) and msg_bar_handler:
                msg_bar_handler.add_msg("Invalid file for branch " + branch)

        return self.branches
    
    def _extract_files_from_html(self, html: str):
        if not html:
            return []

        hits = re.findall(r'\b(?:Price|Promo|PriceFull|PromoFull|Stores)[^"\s<>]+', html)
        cleaned = []
        
        for h in hits:
            h2 = h.strip().strip(',').strip(';').strip(')').strip(']')
            
            if ('.gz' in h2) or h2.endswith('.xml'):
                cleaned.append(h2)
        if cleaned:
            seen = set()
            out = []
            
            for x in cleaned:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            
            return out
        
        return []

    def set_branch_single(self, branch_name, catID="PriceFull", sort="Time", sortdir="ASC", request_method="GET"):
        storeId = self.all_branches.get(branch_name)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": self.site_url,
        }

        try:
            response = self.session.get(self.site_url, headers=headers, timeout=30)
        except Exception:
            return False

        if response.status_code != 200:
            return False

        html = response.text or ""
        files = self._extract_files_from_html(html)
        
        if not files:
            return False

        storeId_str = f"{int(storeId):04d}"
        branch_token = f"-{storeId_str}-"
        candidates = [fn for fn in files if branch_token in str(fn) and str(fn).startswith(str(catID))]
        
        if not candidates:
            return False

        chosen_filename = candidates[0]

        if (chosen_filename.endswith("\\")):
            chosen_filename = chosen_filename[:-1]

        date_folder = chosen_filename.split("/")[-1].split("-")[-1][:8]
        file_url = f"{self.site_url}/{date_folder}/{chosen_filename}"
            
        row_dict = {
            "url": file_url,
            "date": "",
            "type": None,
            "filename": chosen_filename,
            "code": self.session_state.get("branch_filter"),
        }

        self.branches[branch_name] = row_dict
        return True

    def update_url(self, branch_name):
        return update_url(self, branch_name)