# money_menu.py

import os, sqlite3, datetime, sys, re
from typing import List, Tuple

# --------- USTAWIENIA ---------
DB_PATH = os.path.expanduser("~/.local/share/bankdb/bank.db")

FUEL_VENDORS = [
    "orlen", "pkn orlen", "shell", "circle k", "bp", "moya", "lotos",
    "amic", "avia", "total", "statoil", "stacja paliw"
]
PHONE_PHRASES = [
    "przelew na telefon", "blik na telefon", "blik przelew na telefon", "blik p2p"
]
ATM_PHRASES = ["bankomat", "wypłata z bankomatu", "wpłatomat", "atm"]

# --------- RICH (kolory i ramki) ---------
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    from rich.prompt import Prompt
except ImportError:
    print("Brak biblioteki 'rich'. Zainstaluj: pip install --break-system-packages rich")
    sys.exit(1)

console = Console()

# --------- (Opcjonalnie) SALDO z ostatnich maili Inteligo ---------
def try_latest_balance_from_gmail(days:int=14):
    """
    Zwraca ostatnie 'Dostępne środki' (float) z maili Inteligo z ostatnich N dni,
    albo None jeśli nie uda się pobrać.
    """
    try:
        sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))
        import gmail_bridge as gb  # load_service(), gmail_list_all_ids(), _msg_text()
    except Exception:
        return None

    try:
        svc = gb.load_service()
        q = f'from:inteligo@inteligo.pl newer_than:{days}d'
        ids = gb.gmail_list_all_ids(svc, q, max_per_page=200)
        if not ids:
            return None

        best_ts = -1
        best_val = None
        BAL_RE = re.compile(r"Dostępne(?:\s+środki)?\s+([+\-]?\d[\d\s\u00A0]*(?:[.,]\d{2}))\s*(?:PLN|zł)", re.I)

        for mid in ids:
            msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
            ts = int(msg.get("internalDate","0"))
            text = gb._msg_text(msg) or ""
            m = BAL_RE.search(text)
            if m and ts > best_ts:
                raw = m.group(1).replace("\xa0","").replace(" ","").replace(",",".")
                try:
                    best_val = float(raw)
                    best_ts = ts
                except:
                    pass

        return best_val
    except Exception:
        return None

# --------- DB UTILS ---------
def db() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        console.print(f"[red]Nie znaleziono bazy: {DB_PATH}[/red]")
        sys.exit(1)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def q(con: sqlite3.Connection, sql: str, args: Tuple = ()):
    cur = con.cursor()
    cur.execute(sql, args)
    return cur.fetchall()

# --------- POMOC ---------
def this_month() -> str:
    return datetime.datetime.now().strftime("%Y-%m")

def header(title: str) -> None:
    console.print(Panel.fit(f"[bright_green]{title}[/bright_green]", border_style="bright_green"))

def neon_table(title: str, columns: List[Tuple[str, str]], rows: List[Tuple]) -> None:
    t = Table(title=f"[green]{title}[/green]", box=box.DOUBLE_EDGE, style="green")
    for col_title, style in columns:
        t.add_column(col_title, style=style)
    for r in rows:
        t.add_row(*[str(x) for x in r])
    console.print(t)

def like_any(field: str, words: List[str]) -> str:
    return " OR ".join([f"{field} LIKE ?" for _ in words])

def params_any(words: List[str]) -> List[str]:
    return [f"%{w}%" for w in words]

# --------- ZAPYTANIA ---------
def monthly_totals(con: sqlite3.Connection, ym: str):
    income = q(con, "SELECT IFNULL(SUM(amount),0) AS s FROM transactions_final WHERE ym=? AND amount>0", (ym,))[0]["s"]
    outgo  = q(con, "SELECT IFNULL(SUM(-amount),0) AS s FROM transactions_final WHERE ym=? AND amount<0", (ym,))[0]["s"]
    net = float(income) - float(outgo)  # bilans miesiąca (informacyjnie)
    return float(income), float(outgo), net

def list_incomes(con: sqlite3.Connection, ym: str):
    return q(con, """
        SELECT op_date, ROUND(amount,2) AS amount, counterparty, COALESCE(title,'') AS title, source_hint
        FROM transactions_final
        WHERE ym=? AND amount>0
        ORDER BY op_date, amount
    """, (ym,))

def list_expenses(con: sqlite3.Connection, ym: str):
    return q(con, """
        SELECT op_date, ROUND(-amount,2) AS amount, counterparty, COALESCE(title,'') AS title, source_hint
        FROM transactions_final
        WHERE ym=? AND amount<0
        ORDER BY op_date, amount DESC
    """, (ym,))

def list_fuel(con: sqlite3.Connection, ym: str):
    where = like_any("LOWER(counterparty)", FUEL_VENDORS) + " OR " + like_any("LOWER(title)", FUEL_VENDORS)
    sql = f"""
        SELECT op_date, ROUND(-amount,2) AS amount, counterparty, COALESCE(title,'') AS title
        FROM transactions_final
        WHERE ym=? AND amount<0 AND ({where})
        ORDER BY op_date, amount DESC
    """
    params = (ym, *params_any([w.lower() for w in FUEL_VENDORS]), *params_any([w.lower() for w in FUEL_VENDORS]))
    return q(con, sql, params)

def list_atm(con: sqlite3.Connection, ym: str):
    where = like_any("LOWER(counterparty)", ATM_PHRASES) + " OR " + like_any("LOWER(title)", ATM_PHRASES)
    sql = f"""
        SELECT op_date, ROUND(-amount,2) AS amount, counterparty, COALESCE(title,'') AS title
        FROM transactions_final
        WHERE ym=? AND amount<0 AND ({where})
        ORDER BY op_date
    """
    params = (ym, *params_any([w.lower() for w in ATM_PHRASES]), *params_any([w.lower() for w in ATM_PHRASES]))
    return q(con, sql, params)

def list_phone_xfers_out(con: sqlite3.Connection, ym: str):
    where = like_any("LOWER(counterparty)", PHONE_PHRASES) + " OR " + like_any("LOWER(title)", PHONE_PHRASES)
    sql = f"""
        SELECT op_date, ROUND(-amount,2) AS amount, counterparty, COALESCE(title,'') AS title
        FROM transactions_final
        WHERE ym=? AND amount<0 AND ({where})
        ORDER BY op_date
    """
    params = (ym, *params_any([w.lower() for w in PHONE_PHRASES]), *params_any([w.lower() for w in PHONE_PHRASES]))
    return q(con, sql, params)

def list_phone_xfers_in(con: sqlite3.Connection, ym: str):
    where = like_any("LOWER(counterparty)", PHONE_PHRASES) + " OR " + like_any("LOWER(title)", PHONE_PHRASES)
    sql = f"""
        SELECT op_date, ROUND(amount,2) AS amount, counterparty, COALESCE(title,'') AS title
        FROM transactions_final
        WHERE ym=? AND amount>0 AND ({where})
        ORDER BY op_date
    """
    params = (ym, *params_any([w.lower() for w in PHONE_PHRASES]), *params_any([w.lower() for w in PHONE_PHRASES]))
    return q(con, sql, params)

def list_card_no_fuel(con: sqlite3.Connection, ym: str):
    fuel_where = like_any("LOWER(counterparty)", FUEL_VENDORS) + " OR " + like_any("LOWER(title)", FUEL_VENDORS)
    sql = f"""
        SELECT op_date, ROUND(-amount,2) AS amount, counterparty, COALESCE(title,'') AS title
        FROM transactions_final
        WHERE ym=? AND amount<0
          AND (source_hint LIKE 'mail:card_%' OR source_hint='mail:charge')
          AND NOT ({fuel_where})
        ORDER BY op_date
    """
    params = (ym, *params_any([w.lower() for w in FUEL_VENDORS]), *params_any([w.lower() for w in FUEL_VENDORS]))
    return q(con, sql, params)

# --------- WIDOKI / EKRANY ---------
def show_summary(con: sqlite3.Connection, ym: str) -> None:
    # SALDO – z ostatnich maili Inteligo (jeśli brak, pokazujemy „brak danych”)
    saldo = try_latest_balance_from_gmail()
    saldo_txt = f"{saldo:.2f} zł" if saldo is not None else "brak danych"

    income, outgo, _net = monthly_totals(con, ym)

    t = Table(box=box.DOUBLE_EDGE, style="green")
    t.add_column("PKO INTELIGO", style="bright_green")
    t.add_column("Uznania", style="bright_yellow", justify="right")
    t.add_column("Wydatki", style="magenta", justify="right")
    t.add_column("Saldo", style="cyan", justify="right")  # 👈 zamiast „Bilans”
    t.add_row(ym, f"{income:.2f} zł", f"{outgo:.2f} zł", saldo_txt)
    console.print(Panel(t, border_style="bright_green"))

def show_rows(title: str, rows, is_out=False) -> None:
    cols = [("Data", "cyan"), ("Kwota", "bright_yellow"), ("Kontrahent", "green"), ("Tytuł", "green")]
    t = Table(title=f"[green]{title}[/green]", box=box.MINIMAL_DOUBLE_HEAD, style="green")
    for n, s in cols:
        t.add_column(n, style=s)
    for r in rows:
        kw = float(r["amount"])
        kw = -kw if (is_out and kw > 0) else kw
        t.add_row(str(r["op_date"]), f"{kw:.2f} zł", r["counterparty"] or "", r["title"] or "")
    console.print(t)

def menu_screen() -> None:
    con = db()
    ym = this_month()

    while True:
        console.clear()
        header("PKO INTELIGO: podsumowanie miesiąca")
        show_summary(con, ym)

        m = Table(box=box.SQUARE, style="green", title="[green]Wybierz akcję[/green]")
        m.add_column("#", style="bright_yellow", justify="right", no_wrap=True)
        m.add_column("Opis", style="green")

        # Numeracja wg Twoich wymagań:
        options = [
            ("1", "Uznania (szczegóły)"),
            ("2", "Wydatki (szczegóły)"),
            ("3", "Wydatki na stacjach paliw"),
            ("4", "Przelewy na telefon (wychodzące)"),
            ("5", "Przelewy na telefon (przychodzące)"),
            ("6", "Wypłaty z bankomatów"),
            ("7", "Płatności kartą (bez stacji)"),
            ("8", f"Zmień miesiąc (obecnie: {ym})"),
            ("0", "Wyjście")
        ]
        for k, v in options:
            m.add_row(k, v)

        console.print(m)
        choice = Prompt.ask("[bright_green]Wybór[/bright_green]", choices=[x[0] for x in options], default="0")

        if choice == "0":
            console.print("[green]Do zobaczenia.[/green]")
            break
        elif choice == "8":
            new_ym = Prompt.ask("[bright_green]Podaj miesiąc (YYYY-MM)[/bright_green]", default=ym)
            if re.fullmatch(r"\d{4}-\d{2}", new_ym):
                ym = new_ym
            else:
                console.print("[red]Zły format miesiąca.[/red]")
            continue

        # Szczegóły
        if choice == "1":
            rows = list_incomes(con, ym)
            console.clear(); header(f"UZNANIA • {ym}"); show_rows("Uznania", rows, is_out=False)
            Prompt.ask("[green]Enter, by wrócić[/green]")
        elif choice == "2":
            rows = list_expenses(con, ym)
            console.clear(); header(f"WYDATKI • {ym}"); show_rows("Wydatki", rows, is_out=True)
            Prompt.ask("[green]Enter, by wrócić[/green]")
        elif choice == "3":
            rows = list_fuel(con, ym)
            console.clear(); header(f"PALIWO • {ym}"); show_rows("Stacje paliw", rows, is_out=True)
            Prompt.ask("[green]Enter, by wrócić[/green]")
        elif choice == "4":
            rows = list_phone_xfers_out(con, ym)
            console.clear(); header(f"PRZELEWY NA TEL. (WYCHODZĄCE) • {ym}"); show_rows("Przelewy na telefon (wychodzące)", rows, is_out=True)
            Prompt.ask("[green]Enter, by wrócić[/green]")
        elif choice == "5":
            rows = list_phone_xfers_in(con, ym)
            console.clear(); header(f"PRZELEWY NA TEL. (PRZYCHODZĄCE) • {ym}"); show_rows("Przelewy na telefon (przychodzące)", rows, is_out=False)
            Prompt.ask("[green]Enter, by wrócić[/green]")
        elif choice == "6":
            rows = list_atm(con, ym)
            console.clear(); header(f"BANKOMATY • {ym}"); show_rows("Wypłaty z bankomatów", rows, is_out=True)
            Prompt.ask("[green]Enter, by wrócić[/green]")
        elif choice == "7":
            rows = list_card_no_fuel(con, ym)
            console.clear(); header(f"KARTA (bez stacji) • {ym}"); show_rows("Karta bez paliwa", rows, is_out=True)
            Prompt.ask("[green]Enter, by wrócić[/green]")

if __name__ == "__main__":
    menu_screen()
