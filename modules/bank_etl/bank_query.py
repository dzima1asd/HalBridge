"""
bank_query.py — prosty moduł CLI/JSON do odczytu Twojej bazy (~/.local/share/bankdb/bank.db)
Przyjazny dla gpt_chat_v3.py: każda odpowiedź to pojedynczy JSON (lub tablica JSON).

PRZYKŁADY:
  bank_query.py help
  bank_query.py list 2025-09
  bank_query.py list 2025-09 out
  bank_query.py sum_in 2025-09
  bank_query.py sum_out 2025-09
  bank_query.py balance 2025-09
  bank_query.py fuel 2025-09
  bank_query.py card_no_fuel 2025-09
  bank_query.py atm 2025-09
  bank_query.py phone 2025-09
  bank_query.py incomes 2025-09
  bank_query.py expenses 2025-09
  bank_query.py latest 20
  bank_query.py since 2025-09-01
"""

import os, sys, sqlite3, json, re

DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

FUEL_PATTERNS = [
    r"\bORLEN\b", r"\bP(KN\s+)?ORLEN\b", r"\bAVIA\b", r"\bSTACJA\b", r"\bBP\b",
    r"\bSHELL\b", r"\bCIRCLE\s*K\b", r"\bMOYA\b", r"\bLOTOS\b", r"\bAMIC\b", r"\bTOTAL\b"
]
FUEL_RX = re.compile("|".join(FUEL_PATTERNS), re.I)

PHONE_PATTERNS = [r"przelew.*telefon", r"blik.*telefon", r"blik\s*p2p"]
PHONE_RX = re.compile("|".join(PHONE_PATTERNS), re.I)

def q(sql, args=()):
    con = sqlite3.connect(DB)
    try:
        cur = con.cursor()
        cur.execute(sql, args)
        rows = cur.fetchall()
        return rows
    finally:
        con.close()

def jprint(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def err(msg, **extra):
    out = {"error": msg}
    out.update(extra)
    jprint(out)

def help_json():
    cmds = {
        "help": "Ten ekran pomocy.",
        "list <YYYY-MM> [in|out|all]": "Lista transakcji w miesiącu, domyślnie all.",
        "sum_in <YYYY-MM>": "Suma uznań w miesiącu.",
        "sum_out <YYYY-MM>": "Suma wydatków (wartość dodatnia) w miesiącu.",
        "balance <YYYY-MM>": "Suma netto (in - out) w miesiącu.",
        "fuel <YYYY-MM>": "Wydatki na paliwo: lista + suma.",
        "card_no_fuel <YYYY-MM>": "Płatności kartą (autoryzacje) bez stacji: lista + suma.",
        "atm <YYYY-MM>": "Wypłaty z bankomatów: lista + suma.",
        "phone <YYYY-MM>": "Przelewy na telefon (w tym BLIK P2P): lista + suma.",
        "incomes <YYYY-MM>": "Lista uznań (przychodów) w miesiącu.",
        "expenses <YYYY-MM>": "Lista obciążeń (wydatków) w miesiącu.",
        "latest [N]": "N ostatnich transakcji (domyślnie 20) wg created_at.",
        "since <YYYY-MM-DD>": "Wszystko od daty operacji w górę."
    }
    jprint({"usage": "bank_query.py <cmd> [args]", "commands": cmds})

def is_fuel(row):
    # row: (op_date, amount, title, counterparty, source_hint)
    title, cp = row[2] or "", row[3] or ""
    text = f"{title} {cp}"
    return FUEL_RX.search(text) is not None

def is_phone(row):
    title, cp = row[2] or "", row[3] or ""
    text = f"{title} {cp}".lower()
    return PHONE_RX.search(text) is not None

def list_month(month, direction="all"):
    if direction not in ("all","in","out"):
        return err("bad_direction", allowed=["all","in","out"])
    base_sql = "SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=?"
    args = [month]
    if direction == "in":
        base_sql += " AND amount>0"
    elif direction == "out":
        base_sql += " AND amount<0"
    base_sql += " ORDER BY op_date, amount"
    rows = q(base_sql, args)
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in rows]
    jprint({"month": month, "direction": direction, "rows": data, "count": len(data)})

def sum_in(month):
    rows = q("SELECT ROUND(SUM(amount),2) FROM transactions_final WHERE ym=? AND amount>0", (month,))
    total = rows[0][0] or 0
    jprint({"month": month, "sum_in": total})

def sum_out(month):
    rows = q("SELECT ROUND(SUM(-amount),2) FROM transactions_final WHERE ym=? AND amount<0", (month,))
    total = rows[0][0] or 0
    jprint({"month": month, "sum_out": total})

def balance(month):
    rows = q("SELECT ROUND(SUM(amount),2) FROM transactions_final WHERE ym=?", (month,))
    total = rows[0][0] or 0
    jprint({"month": month, "balance": total})

def fuel_month(month):
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=? AND amount<0", (month,))
    picked = [r for r in rows if is_fuel(r)]
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in picked]
    total = round(sum(-r["amount"] for r in data), 2)
    jprint({"month": month, "category": "fuel", "sum_out": total, "rows": data, "count": len(data)})

def card_no_fuel(month):
    # Źródło z autoryzacji kartowych, ale odfiltruj stacje
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=? AND amount<0 AND source_hint='mail:card_auth'", (month,))
    picked = [r for r in rows if not is_fuel(r)]
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in picked]
    total = round(sum(-r["amount"] for r in data), 2)
    jprint({"month": month, "category": "card_no_fuel", "sum_out": total, "rows": data, "count": len(data)})

def atm_month(month):
    # Proste heurystyki: "bankomat", "ATM", "wypłata"
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=? AND amount<0", (month,))
    picked = []
    for r in rows:
        text = f"{(r[2] or '')} {(r[3] or '')}".lower()
        if "bankomat" in text or "atm" in text or "wypłata" in text:
            picked.append(r)
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in picked]
    total = round(sum(-r["amount"] for r in data), 2)
    jprint({"month": month, "category": "atm", "sum_out": total, "rows": data, "count": len(data)})

def phone_month(month):
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=? AND amount<0", (month,))
    picked = [r for r in rows if is_phone(r)]
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in picked]
    total = round(sum(-r["amount"] for r in data), 2)
    jprint({"month": month, "category": "phone_transfer", "sum_out": total, "rows": data, "count": len(data)})

def incomes_month(month):
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=? AND amount>0 ORDER BY op_date, amount", (month,))
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in rows]
    total = round(sum(r["amount"] for r in data), 2)
    jprint({"month": month, "direction": "in", "sum_in": total, "rows": data, "count": len(data)})

def expenses_month(month):
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE ym=? AND amount<0 ORDER BY op_date, amount", (month,))
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in rows]
    total = round(sum(-r["amount"] for r in data), 2)
    jprint({"month": month, "direction": "out", "sum_out": total, "rows": data, "count": len(data)})

def latest(n=20):
    try:
        n = int(n)
    except:
        n = 20
    rows = q("SELECT op_date, amount, title, counterparty, source_hint, created_at FROM transactions_final ORDER BY datetime(created_at) DESC LIMIT ?", (n,))
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4], "created_at":r[5]} for r in rows]
    jprint({"limit": n, "rows": data, "count": len(data)})

def since(date_ymd):
    rows = q("SELECT op_date, amount, title, counterparty, source_hint FROM transactions_final WHERE op_date>=? ORDER BY op_date, amount", (date_ymd,))
    data = [{"date":r[0], "amount":r[1], "title":r[2], "counterparty":r[3], "src":r[4]} for r in rows]
    jprint({"since": date_ymd, "rows": data, "count": len(data)})

def main():
    if len(sys.argv) < 2:
        return help_json()

    cmd = sys.argv[1]
    arg1 = sys.argv[2] if len(sys.argv) > 2 else None
    arg2 = sys.argv[3] if len(sys.argv) > 3 else None

    if cmd == "help":
        return help_json()
    elif cmd == "list":
        if not arg1: return err("need_month")
        direction = arg2 or "all"
        return list_month(arg1, direction)
    elif cmd == "sum_in":
        if not arg1: return err("need_month")
        return sum_in(arg1)
    elif cmd == "sum_out":
        if not arg1: return err("need_month")
        return sum_out(arg1)
    elif cmd == "balance":
        if not arg1: return err("need_month")
        return balance(arg1)
    elif cmd == "fuel":
        if not arg1: return err("need_month")
        return fuel_month(arg1)
    elif cmd == "card_no_fuel":
        if not arg1: return err("need_month")
        return card_no_fuel(arg1)
    elif cmd == "atm":
        if not arg1: return err("need_month")
        return atm_month(arg1)
    elif cmd == "phone":
        if not arg1: return err("need_month")
        return phone_month(arg1)
    elif cmd == "incomes":
        if not arg1: return err("need_month")
        return incomes_month(arg1)
    elif cmd == "expenses":
        if not arg1: return err("need_month")
        return expenses_month(arg1)
    elif cmd == "latest":
        n = arg1 or "20"
        return latest(n)
    elif cmd == "since":
        if not arg1: return err("need_date_YYYY-MM-DD")
        return since(arg1)
    else:
        return err("unknown_cmd")

if __name__ == "__main__":
    main()
