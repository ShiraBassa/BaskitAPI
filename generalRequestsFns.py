cities = {
    "תל אביב": 'ת"א',
    "באר שבע": 'ב"ש',
    "ראשון לציון": 'ראשל"צ',
    "פתח תקווה": 'פ"ת',
    "כפר סבא": 'כ"ס',
    "אשקלון": None,
    "בית שמש": None,
    "נתניה": None
}

ILLEGAL_FIREBASE_CHARS = {'.', '$', '#', '[', ']', '/'}


def getCities(abbr=False):
    if not abbr:
        return list(cities.keys())
    
    return cities

def getAbbr(key):
    if key in cities:
        return cities[key]
    
    return None

def get_branches(handler, cities):
    branches = []
    
    for branch_name in handler.all_branches:
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

def update_url(self, branch_name):
    self.set_branch_single(branch_name, self.branches[branch_name]["type"])
    return self.branches[branch_name]["url"]

def sanitize_key(key: str) -> str:
    for ch in ILLEGAL_FIREBASE_CHARS:
        key = key.replace(ch, "_")
    return key