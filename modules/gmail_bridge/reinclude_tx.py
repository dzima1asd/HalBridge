#!/usr/bin/env python3
import sqlite3, argparse
from pathlib import Path

DB = Path("~/.local/share/bankdb/bank.db").expanduser()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rowid", type=int, required=True, help="ROWID do białej listy")
    ap.add_argument("--ym", required=True, help='Miesiąc "YYYY-MM" do kontroli (np. 2025-01)')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 0) Czy mamy widok transactions_clean?
    ok = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='transactions_clean';"
    ).fetchone()
    if not ok:
        print("[BŁĄD] Brak widoku transactions_clean – uruchom najpierw mk_view_clean.py")
        return

    try:
        cur.execute("BEGIN IMMEDIATE;")
        # 1) Tabela białej listy (raz tworzona)
        cur.execute("CREATE TABLE IF NOT EXISTS tx_reinclude AS SELECT * FROM transactions_canon WHERE 0;")
        # 2) Dopisz wskazany rekord do białej listy
        cur.execute("INSERT OR IGNORE INTO tx_reinclude SELECT * FROM transactions_canon WHERE rowid=?;", (args.rowid,))
        # 3) Odtwórz widok końcowy = transactions_clean + biała lista (bez duplikatów po tx_hash)
        cur.execute("DROP VIEW IF EXISTS transactions_final;")
        cur.execute("""
            CREATE VIEW transactions_final AS
            SELECT * FROM transactions_clean
            UNION ALL
            SELECT t.*
            FROM tx_reinclude t
            LEFT JOIN transactions_clean c USING (tx_hash)
            WHERE c.tx_hash IS NULL;
        """)
        con.commit()
    except Exception as e:
        con.rollback()
        print("[BŁĄD]", e)
        return

    # Kontrola: suma w clean vs final dla podanego miesiąca
    clean_sum = cur.execute(
        "SELECT printf('%.2f', COALESCE(SUM(amount),0)) FROM transactions_clean WHERE ym=? AND lower(direction)='kredyt';",
        (args.ym,)
    ).fetchone()[0]
    final_sum = cur.execute(
        "SELECT printf('%.2f', COALESCE(SUM(amount),0)) FROM transactions_final WHERE ym=? AND lower(direction)='kredyt';",
        (args.ym,)
    ).fetchone()[0]

    print(f"[OK] Dodano rowid={args.rowid} do białej listy. YM={args.ym}  clean_sum={clean_sum}  final_sum={final_sum}")

if __name__ == "__main__":
    main()
