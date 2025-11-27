import os, re, sys, base64, datetime
from collections import defaultdict
from email.utils import parseaddr
from bs4 import BeautifulSoup
from html2text import html2text

from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

CONF = os.path.expanduser("~/.config/gmail_bridge")
CREDS_JSON = os.path.join(CONF, "client_secret.json")
TOKEN_JSON = os.path.join(CONF, "token.json")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

FUEL_VENDORS = ["orlen", "pkn orlen", "shell", "circle k", "bp", "moya", "lotos", "amic", "avia", "total", "watis", "wasbrs", "petrol", "statoil"]
ATM_KEYWORDS = ["wypłata z bankomatu", "wplatomat", "bankomat", "atm"]
PHONE_XFER = ["przelew na telefon", "blik na telefon", "blik przelew na telefon", "blik p2p"]
CARD_KEYWORDS = ["płatność kartą", "transakcja kartą", "visa", "mastercard", "pos"]

AMOUNT_RE = re.compile(r"([+-]?\d[\d\s\u00A0]{0,12}(?:[.,]\d{2})?)[\s\u00A0]*(?:zł|PLN)\b", re.I)

def load_service():
    os.makedirs(CONF, exist_ok=True)
    creds = None
    if os.path.exists(TOKEN_JSON):
        creds = Credentials.from_authorized_user_file(TOKEN_JSON, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_JSON):
                print("@#@Brak pliku client_secret.json. Skopiuj go do ~/.config/gmail_bridge i uruchom ponownie: gmailctl init@#@")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_JSON, SCOPES)
            creds = flow.run_console()
        with open(TOKEN_JSON, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def _msg_text(msg):
    payload = msg.get("payload", {})
    def walk(p):
        if "data" in p.get("body", {}) and p.get("mimeType", "").startswith("text/"):
            data = base64.urlsafe_b64decode(p["body"]["data"]).decode(errors="ignore")
            if p["mimeType"] == "text/html":
                try:
                    return html2text(data)
                except Exception:
                    return BeautifulSoup(data, "html.parser").get_text(" ")
            return data
        for part in p.get("parts", []) or []:
            t = walk(part)
            if t: return t
        return ""
    return walk(payload) or (msg.get("snippet") or "")

def _header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""

def _orig_sender(msg):
    frm = _header(msg, "From") or ""
    name, addr = parseaddr(frm)
    body = _msg_text(msg)
    m = re.search(r"^From:\s*(.+?)\s*<([^>]+)>", body, re.I | re.M)
    if m:
        name2, addr2 = m.group(1).strip(), m.group(2).strip()
        if addr2 and "forward" in (_header(msg, "Subject") + " " + body).lower():
            return (name2, addr2.lower())
    return (name or addr.split("@")[0], (addr or "").lower())

def _amounts(text):
    vals = []
    for m in AMOUNT_RE.finditer(text):
        s = m.group(1).replace(" ", "").replace("\xa0", "").replace(",", ".")
        try:
            vals.append(round(float(s), 2))
        except:
            pass
    return vals

def _month(ts_ms):
    dt = datetime.datetime.fromtimestamp(int(ts_ms) / 1000)
    return dt.strftime("%Y-%m")

def list_senders(svc, query):
    senders = defaultdict(int)
    pageToken = None
    while True:
        res = svc.users().messages().list(userId="me", q=query, pageToken=pageToken, maxResults=500).execute()
        for it in res.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=it["id"], format="full").execute()
            name, addr = _orig_sender(msg)
            key = f"{name} <{addr}>".strip()
            senders[key] += 1
        pageToken = res.get("nextPageToken")
        if not pageToken: break
    for s, c in sorted(senders.items(), key=lambda x: (-x[1], x[0])):
        print(f"{c:5d}  {s}")

def classify_entry(subj, body):
    text = f"{subj}\n{body}".lower()
    if any(k in text for k in ATM_KEYWORDS): return "atm"
    if any(k in text for k in PHONE_XFER): return "phone_transfer"
    if any(v in text for v in FUEL_VENDORS): return "fuel"
    if "wpływ" in text or "uznanie" in text or "zasilenie" in text or "przelew przychodzący" in text: return "income"
    if any(k in text for k in CARD_KEYWORDS) or "obciążenie" in text or "płatność" in text or "przelew wychodzący" in text: return "card"
    return "unknown"

def aggregate_finance(svc, query):
    data = defaultdict(lambda: defaultdict(float))
    unknown = []
    pageToken = None
    while True:
        res = svc.users().messages().list(userId="me", q=query, pageToken=pageToken, maxResults=200).execute()
        for it in res.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=it["id"], format="full").execute()
            subj = _header(msg, "Subject")
            body = _msg_text(msg)
            cat = classify_entry(subj, body)
            amts = _amounts(body + "\n" + subj)
            if not amts: continue
            amount = max(amts)
            ym = _month(msg.get("internalDate", "0"))
            data[ym][cat] += amount
            if cat == "unknown":
                sn = (_header(msg, "From") or "").strip()
                unknown.append((ym, amount, subj[:120], sn))
        pageToken = res.get("nextPageToken")
        if not pageToken: break
    return data, unknown

def print_monthly_income(svc):
    data, _ = aggregate_finance(svc, "newer_than:2y")
    for ym in sorted(data.keys()):
        val = data[ym].get("income", 0.0)
        print(f"{ym}  {val:.2f} zł")

def print_expenses_breakdown(svc):
    data, unknown = aggregate_finance(svc, "newer_than:2y")
    for ym in sorted(data.keys()):
        total = sum(v for k, v in data[ym].items() if k != "income")
        fuel = data[ym].get("fuel", 0.0)
        atm = data[ym].get("atm", 0.0)
        phone = data[ym].get("phone_transfer", 0.0)
        card = data[ym].get("card", 0.0)
        non_fuel_card = max(card - fuel, 0.0)
        print(f"{ym}  TOTAL:{total:.2f}  paliwo:{fuel:.2f}  bankomat:{atm:.2f}  telprzelew:{phone:.2f}  karta_bez_paliwa:{non_fuel_card:.2f}")
    if unknown:
        print("@#@Są transakcje niezidentyfikowane. Odpowiedz wzorcem: classify;<YYYY-MM>;<kwota>;<kategoria>;<opis>. Kategorie: income,fuel,atm,phone_transfer,card.@#@")
        for ym, amt, subj, sn in unknown[:30]:
            print(f"??? {ym}  {amt:.2f} zł  {sn}  {subj}")

def main():
    if len(sys.argv) < 2:
        print("Usage: gmailctl <init|who|income|expenses> [query]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "init":
        svc = load_service()
        print("@#@Autoryzacja zakończona.@#@")
        return
    svc = load_service()
    if cmd == "who":
        q = sys.argv[2] if len(sys.argv) > 2 else "newer_than:2y"
        list_senders(svc, q)
    elif cmd == "income":
        print_monthly_income(svc)
    elif cmd == "expenses":
        print_expenses_breakdown(svc)
    else:
        print("Unknown command")

if __name__ == "__main__":
    main()
