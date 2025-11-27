import re

TIME_REGEX = r"(\b\d{1,2}[:\.]\d{2}\b|\bsiódma rano\b|\b7 rano\b)"
NUMBER_REGEX = r"\b(\d+)\b"
DEVICE_REGEX = r"(światło\s*\d+)"

def normalize_time(text):
    text = text.lower()
    if "siódma rano" in text or "7 rano" in text:
        return "07:00"
    m = re.search(r"(\d{1,2})[:\.](\d{2})", text)
    if m:
        h, mnt = m.group(1), m.group(2)
        return f"{int(h):02d}:{int(mnt):02d}"
    return None

def extract_slots(text: str, intent: str):
    slots = {}

    # urządzenie
    m = re.search(DEVICE_REGEX, text.lower())
    if m:
        slots["device"] = m.group(1)

    # czas
    t = normalize_time(text)
    if t:
        slots["time"] = t

    # interwały i liczby
    nums = re.findall(NUMBER_REGEX, text)
    if nums:
        slots["numbers"] = [int(x) for x in nums]

    return slots
