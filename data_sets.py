cities = {
    "תל אביב": 'ת"א',
    "באר שבע": 'ב"ש',
    "ראשון לציון": 'ראשל"צ',
    "פתח תקווה": 'פ"ת',
    "כפר סבא": 'כ"ס',
}


def getCities(abbr=False):
    if not abbr:
        return list(cities.keys())
    
    return cities

def getAbbr(key):
    if key in cities:
        return cities[key]
    
    return None