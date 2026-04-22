@staticmethod
def detect_type(value):
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, str):
        val = value.strip()
        if val.lower() in ['true', 'false']:
            return 'boolean'
        try:
            int(val)
            return 'integer'
        except ValueError:
            pass
        try:
            float(val)
            return 'float'
        except ValueError:
            pass
        return 'string'
    return 'unknown'
