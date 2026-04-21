import re

TIME_REGEX = r"(\b\d{1,2}[:\.]\d{2}\b|\bsiódma rano\b|\b7 rano\b)"
NUMBER_REGEX = r"\b(\d+)\b"
DEVICE_REGEX = r"(światło\s*\d+|swiatlo\s*\d+|światło|swiatlo)"

def normalize_time(text):
    text = text.lower()
    if "siódma rano" in text or "7 rano" in text:
        return "07:00"
    m = re.search(r"(\d{1,2})[:\.](\d{2})", text)
    if m:
        h, mnt = m.group(1), m.group(2)
        return f"{int(h):02d}:{int(mnt):02d}"
    return None

def normalize_device(device: str) -> str:
    d = (device or "").lower().strip()
    d = d.replace("światło", "swiatlo")
    d = re.sub(r"\s+", " ", d)
    return d

def extract_slots(text: str, intent: str):
    slots = {}
    text_l = text.lower().strip()

    m = re.search(DEVICE_REGEX, text_l)
    if m:
        slots["device"] = normalize_device(m.group(1))

    t = normalize_time(text)
    if t:
        slots["time"] = t

    nums = re.findall(NUMBER_REGEX, text)
    if nums:
        slots["numbers"] = [int(x) for x in nums]

    if intent == "iot.toggle":
        if re.search(r"\b(włącz|wlacz)\b", text_l):
            slots["desired_state"] = "on"
        elif re.search(r"\b(wyłącz|wylacz)\b", text_l):
            slots["desired_state"] = "off"

    if intent == "mail.search":
        q = re.sub(r"^\s*(znajdź w mailach|znajdz w mailach|szukaj maili|szukaj w mailach)\s*", "", text_l)
        q = q.strip()
        if q:
            slots["query"] = q

    elif intent == "browser.fetch":
        q = re.sub(r"^\s*(pobierz stronę|pobierz strone|fetch)\s*", "", text_l)
        q = q.strip()
        if q:
            slots["query"] = q

    elif intent == "system.exec":
        q = re.sub(r"^\s*(wykonaj komendę|wykonaj komende|uruchom komendę|uruchom komende|system)\s*", "", text_l)
        q = q.strip()
        if q:
            slots["command"] = q

    return slots
