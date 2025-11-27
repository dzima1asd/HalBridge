from modules.metrics import load_all

def show_dashboard():
    m = load_all()
    return (
        "=== Intent Engine Dashboard ===\n"
        f"Intent OK:       {m.get('intent_ok')}\n"
        f"Intent Fail:     {m.get('intent_fail')}\n"
        f"Slot Filled:     {m.get('slot_fill')}\n"
        f"Slot Missing:    {m.get('slot_missing')}\n"
    )
