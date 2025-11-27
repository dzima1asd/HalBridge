#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_ingest.py – kompleksowa diagnostyka pętli Gmail → SQLite → money

Co sprawdzamy:
1) systemd --user: timer + ostatnie logi usługi + wymuszone uruchomienie
2) Gmail: proste zapytanie o 'UZNANIE' (ostatnie N dni)
3) SQLite:
   - ostatnie wpływy (24h)
   - obecność kwoty sondy (domyślnie 250.29) ±0.01 w ciągu 7 dni
   - spójność ym dla rekordów z ostatnich 48h
   - porównanie „Uznania (z ym)” vs „Uznania (bez ym)”
   - widoki jak w money_menu.py (uznania, z opcją wykluczenia przelewów na telefon)
4) money_menu.py: czy DB_PATH wskazuje na tę samą bazę

Użycie:
  python3 diagnose_ingest.py [--days 3] [--probe-amount 250.29] [--db ~/.local/share/bankdb/bank.db]
"""

import os, sys, re, json, subprocess, sqlite3, datetime, argparse
from textwrap import dedent

DEFAULT_DB = os.path.expanduser("~/.local/share/bankdb/bank.db")
MONEY_MENU  = os.path.expanduser("~/HALbridge/modules/bank_etl/money_menu.py")
GMAIL_DIR   = os.path.expanduser("~/HALbridge/modules/gmail_bridge")

def run(cmd: str) -> tuple[int,str,str]:
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out.strip(), err.strip()

def header(txt: str):
    line = "─" * 78
    print(f"\n{line}\n▶ {txt}\n{line}")

def print_table(title: str, txt: str):
    header(title)
    print(txt if txt.strip() else "(brak danych)")

def check_timer_service() -> dict:
    res = {}

    # TIMER
    rc, out, err = run("systemctl --user list-timers gmail-ingest.timer --no-pager || true")
    print_table("TIMER", out)
    res["timer"] = "PASS" if "gmail-ingest.timer" in out else "FAIL"

    # SERVICE last logs
    rc, out, err = run("journalctl --user -u gmail-ingest.service -n 20 --no-pager || true")
    print_table("SERVICE: ostatnie logi", out)
    res["service_last"] = ("PASS", _parse_counters(out)) if "@#@Ingest OK." in out else ("WARN", [0,0])

    # SERVICE forced run
    run("systemctl --user start gmail-ingest.service || true")
    rc, out2, err2 = run("journalctl --user -u gmail-ingest.service -n 6 --no-pager || true")
    print_table("SERVICE: wymuszone uruchomienie", out2)
    res["service_run_now"] = ("PASS", _parse_counters(out2)) if "@#@Ingest OK." in out2 else ("FAIL", [0,0])
    return res

def _parse_counters(log: str):
    # szukamy "@#@Ingest OK. Dodane: X, reszta (update/skip): Y@#@"
    m = re.findall(r"@#@Ingest OK\. Dodane:\s*(\d+),\s*reszta \(update/skip\):\s*(\d+)@#@", log)
    if m:
        x, y = m[-1]
        return [int(x), int(y)]
    return [0,0]

def check_gmail(days: int) -> dict:
    res = {}
    try:
        sys.path.insert(0, GMAIL_DIR)
        import gmail_bridge as gb
        svc = gb.load_service()
        # Najpierw próbujemy zawęzić do Inteligo, potem fallback na subject:
        q1 = f"from:inteligo@inteligo.pl subject:UZNANIE newer_than:{days}d"
        ids1 = gb.gmail_list_all_ids(svc, q1, max_per_page=100) or []
        q2 = f"subject:UZNANIE newer_than:{days}d"
        ids2 = [] if ids1 else (gb.gmail_list_all_ids(svc, q2, max_per_page=100) or [])

        header("GMAIL: szukam 'UZNANIE' z %sd (Inteligo i fallback)" % days)
        print(f"Zapytanie: [{q1}] → znaleziono: {len(ids1)}")
        if not ids1:
            print(f"Zapytanie: [{q2}] → znaleziono: {len(ids2)}")
        ids = ids1 if ids1 else ids2
        if not ids:
            print("(nie znaleziono żadnego maila z 'UZNANIE' w ostatnich %s dniach)" % days)
        else:
            for mid in ids[:5]:
                m = svc.users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["Subject","Date"]).execute()
                subj = gb._header(m,"Subject") or ""
                date = gb._header(m,"Date") or ""
                print(f"- {mid} | {date} | {subj}")

        res["gmail_seen"] = ids
        res["gmail"] = "PASS" if ids else "FAIL"
        return res
    except Exception as e:
        header("GMAIL: błąd")
        print(repr(e))
        res["gmail_seen"] = []
        res["gmail"] = "FAIL"
        return res

def db_connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con

def check_sqlite(db_path: str, probe_amount: float) -> dict:
    res = {}
    con = db_connect(db_path)
    cur = con.cursor()

    # Ostatnie wpływy 24h
    rows = cur.execute(dedent("""
        SELECT op_date, ROUND(amount,2) AS kwota, counterparty, title, source_hint, created_at
          FROM transactions_final
         WHERE amount > 0
           AND created_at >= datetime('now','-24 hours')
         ORDER BY created_at DESC
         LIMIT 30
    """)).fetchall()
    header("SQLITE: ostatnie wpływy (24h)")
    for r in rows:
        print(f"{r['op_date']} | {r['kwota']:.2f} | {r['counterparty']} | {r['title']} | {r['source_hint']} | {r['created_at']}")
    res["sqlite_recent"] = [dict(r) for r in rows]

    # Szukamy kwoty sondy ±0.01 w 7d
    around = cur.execute(dedent("""
        SELECT op_date, amount, counterparty, title, source_hint, created_at
          FROM transactions_final
         WHERE amount BETWEEN ?-0.01 AND ?+0.01
           AND created_at >= datetime('now','-7 days')
         ORDER BY created_at DESC
         LIMIT 1
    """), (probe_amount, probe_amount)).fetchone()

    header(f"SQLITE: szukanie {probe_amount:.2f} (±0,01) w 7d")
    if around:
        print("ZNALEZIONO:", dict(around))
        res["sqlite_around_probe"] = dict(around)
    else:
        print("Nie znaleziono tej kwoty w ostatnich 7 dniach.")
        res["sqlite_around_probe"] = None

    # Spójność ym dla ostatnich 48h
    bad_ym = cur.execute(dedent("""
        SELECT id, op_date, ym, amount, source_hint, created_at
          FROM transactions_final
         WHERE created_at >= datetime('now','-48 hours')
           AND (ym IS NULL OR ym='' OR ym != substr(op_date,1,7))
         ORDER BY created_at DESC
    """)).fetchall()
    header("SQLITE: spójność ym (ostatnie 48h)")
    if bad_ym:
        for r in bad_ym:
            print(f"BAD ym: id={r['id']} op_date={r['op_date']} ym={r['ym']} amount={r['amount']} src={r['source_hint']} created={r['created_at']}")
        res["ym_ok"] = "FAIL"
        res["ym_bad_rows"] = [dict(r) for r in bad_ym]
    else:
        print("OK – brak niezgodności ym.")
        res["ym_ok"] = "PASS"
        res["ym_bad_rows"] = []

    # Porównanie „Uznania z ym” vs „Uznania bez ym”
    ym_now = datetime.datetime.now().strftime("%Y-%m")
    rows_with_ym = cur.execute(dedent("""
        SELECT COUNT(*) AS n
          FROM transactions_final
         WHERE ym=? AND amount>0
    """), (ym_now,)).fetchone()["n"]
    rows_no_ym = cur.execute(dedent("""
        SELECT COUNT(*) AS n
          FROM transactions_final
         WHERE amount>0
           AND op_date >= date(?, '-start of month')
           AND op_date <  date(?, '+1 month', '-start of month')
    """), (ym_now, ym_now)).fetchone()["n"]

    header("SQLITE: Uznania z ym vs bez ym (bieżący miesiąc)")
    print(f"z ym     : {rows_with_ym}")
    print(f"bez ym   : {rows_no_ym}")
    res["credit_counts"] = {"ym": rows_with_ym, "no_ym": rows_no_ym}

    # Widok jak w money_menu.py – Uznania (z wykluczeniem przelewów na telefon)
    money_view = cur.execute(dedent("""
        SELECT op_date, ROUND(amount,2) AS amount, counterparty, COALESCE(title,'') AS title, source_hint
          FROM transactions_final
         WHERE ym=? AND amount>0
           AND NOT (category='phone_transfer' OR source_hint='mail:phone')
         ORDER BY op_date, amount
         LIMIT 50
    """), (ym_now,)).fetchall()
    header("SQLITE: widok 'Uznania' jak w money (bez przelewów na telefon)")
    if money_view:
        for r in money_view[:20]:
            print(f"{r['op_date']} | {r['amount']:.2f} | {r['counterparty']} | {r['title']} | {r['source_hint']}")
    else:
        print("(pusto)")

    res["money_credits_sample"] = [dict(r) for r in money_view[:20]]

    con.close()
    return res

def check_money_dbpath(db_path: str) -> dict:
    res = {"money_dbpath_exists": False, "money_dbpath": None, "match": "UNKNOWN"}
    header("money_menu.py: weryfikacja DB_PATH")
    if not os.path.exists(MONEY_MENU):
        print(f"(brak pliku {MONEY_MENU})")
        res["match"] = "WARN"
        return res
    txt = open(MONEY_MENU, "r", encoding="utf-8").read()
    m = re.search(r'DB_PATH\s*=\s*os\.path\.expanduser\([\'"](.+?)[\'"]\)', txt)
    if not m:
        print("Nie znaleziono definicji DB_PATH w money_menu.py")
        res["match"] = "FAIL"
        return res
    money_db = os.path.expanduser(m.group(1))
    res["money_dbpath"] = money_db
    res["money_dbpath_exists"] = os.path.exists(money_db)
    print(f"DB w money: {money_db} (istnieje: {res['money_dbpath_exists']})")
    print(f"DB w diag : {db_path} (istnieje: {os.path.exists(db_path)})")
    res["match"] = "PASS" if os.path.abspath(money_db) == os.path.abspath(db_path) else "FAIL"
    if res["match"] == "FAIL":
        print("!! money_menu.py wskazuje na inną bazę niż używana w diagnostyce.")
    return res

def summarize(allres: dict):
    header("SPRAWOZDANIE (PASS/FAIL)")
    def pf(x): return x if isinstance(x,str) else x[0]
    print(f"Timer aktywny            : {allres['timer']['timer']}")
    print(f"Service (ostatnie logi)  : {pf(allres['timer']['service_last'])}")
    print(f"Service (run now)        : {pf(allres['timer']['service_run_now'])}")
    print(f"Gmail widzi 'UZNANIE'    : {allres['gmail']['gmail']}")
    print(f"SQLite (spójność ym)     : {allres['sqlite']['ym_ok']}")
    print(f"money DB_PATH zgodny     : {allres['money_db']['match']}")

    # Podpowiedzi
    print("\nDiagnoza:")
    if allres['gmail']['gmail'] == "FAIL":
        print("- Gmail nie zwrócił maili 'UZNANIE' dla bieżącego okna – sprawdź filtr/etykiety albo zwiększ --days.")
    if allres['sqlite']['ym_ok'] == "FAIL":
        print("- W bazie są rekordy z nieprawidłowym ym (ostatnie 48h) – uruchom self-heal:")
        print("  sqlite3 ~/.local/share/bankdb/bank.db \"UPDATE transactions_final SET ym=substr(op_date,1,7) WHERE (ym IS NULL OR ym='') AND op_date IS NOT NULL;\"")
    if allres['money_db']['match'] == "FAIL":
        print("- money_menu.py używa innej ścieżki bazy niż tu – ujednolić DB_PATH.")
    ym = allres['sqlite']['credit_counts']
    if ym['ym'] < ym['no_ym']:
        print("- Uznania (z ym) < Uznania (bez ym) – część rekordów może mieć puste/niepoprawne ym i nie wchodzi do widoku money.")

    # JSON z wynikami (do debug)
    print("\n(JSON z wynikami – do debug):")
    safe = {
        "timer": allres["timer"],
        "gmail": {k:v for k,v in allres["gmail"].items() if k in ("gmail_seen","gmail")},
        "sqlite": {
            "ym_ok": allres["sqlite"]["ym_ok"],
            "credit_counts": allres["sqlite"]["credit_counts"],
            "sqlite_around_probe": allres["sqlite"]["sqlite_around_probe"],
        },
        "money_db": allres["money_db"],
    }
    print(json.dumps(safe, indent=2, ensure_ascii=False))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="Ile dni do tyłu sprawdzać maile 'UZNANIE'")
    ap.add_argument("--probe-amount", type=float, default=250.29, help="Kwota sondy (±0.01) do sprawdzenia w bazie (7d)")
    ap.add_argument("--db", default=DEFAULT_DB, help="Ścieżka bazy SQLite")
    args = ap.parse_args()

    header("START")
    print(f"DB: {args.db}")
    print(f"Okno Gmail: {args.days}d, kwota sondy: {args.probe_amount:.2f}")

    res_timer = check_timer_service()
    res_gmail = check_gmail(args.days)
    res_sqlite = check_sqlite(args.db, args.probe_amount)
    res_money  = check_money_dbpath(args.db)

    allres = {"timer":res_timer, "gmail":res_gmail, "sqlite":res_sqlite, "money_db":res_money}
    summarize(allres)

if __name__ == "__main__":
    main()
