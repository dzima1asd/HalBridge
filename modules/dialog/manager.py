def need_slot(schema: dict, slots: dict):
    missing = []
    for r in schema.get("required", []):
        if r not in slots:
            missing.append(r)
    return missing

def ask_for_missing(missing: list):
    if not missing:
        return None
    # bierzemy pierwszy brakujący parametr
    return f"Brakuje parametru: {missing[0]}"
