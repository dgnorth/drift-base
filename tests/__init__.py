

def has_key(json, key):
    if isinstance(json, list):
        for item in json:
            if has_key(item, key):
                return True
    elif isinstance(json, dict):
        for (k, v) in json.items():
            if k == key:
                return True
            else:
                if has_key(v, key):
                    return True
    return False
