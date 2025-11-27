#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
from pathlib import Path
import argparse
import sys

DB_DEFAULT = Path("~/.local/share/bankdb/bank.db").expanduser()

VIEW_SQL = r"""
DROP VIEW IF EXISTS transactions_clean;
CREATE VIEW transactions_clean AS
SELECT *
FROM transactions_canon
WHERE
  -- wytnij podsumowania/saldo/razem/bilans itp.
  NOT (
    lower(coalesce(title,'')) LIKE '%saldo%' OR
    lower(coalesce(title,'')) LIKE '%suma%'  OR
    lower(coalesce(title,'')) LIKE '%razem%' OR
    lower(coalesce(title,'')) LIKE '%podsum%' OR
    lower(coalesce(title,'')) LIKE '%podsumowanie%' OR
    lower(coalesce(title,'')) LIKE '%zestawienie%' OR
    lower(coalesce(title,'')) LIKE '%bilans%' OR
    lower(coalesce(title,'')) LIKE '%przeniesienie%' OR
    lower(coalesce(title,'')) LIKE '%stan konta%' OR
    lower(coalesce(title,'')) LIKE '%dostępne%' OR
    lower(coalesce(title,'')) LIKE '%dostepne%'
  )
  -- wytnij TYLKO ujemne tytuły czysto liczbowe (np. "−19 067,66")
  AND NOT (
    substr(
      ltrim(replace(replace(coalesce(title,''),' ',''), char(160), '')),
      1, 1
    ) IN ('-','−')
    AND coalesce(title,'') NOT GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*'
  );
"""

def create_view(db_path: Path):
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(VIEW_SQL)
        con.commit()
    finally:
        con.close()

def sum_month(db_path: Path, ym: str) -> float:
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "SELECT COALESCE(SUM(amount),0.0) FROM transactions_clean "
            "WHERE ym=? AND lower(direction)='kredyt';",
            (ym,)
        )
        (val,) = cur.fetchone()
        return float(val or 0.0)
    finally:
        con.close()

def list_year(db_path: Path, year: str):
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "SELECT ym, printf('%.2f', SUM(CASE WHEN lower(direction)='kredyt' "
            "THEN amount ELSE 0 END)) AS przychody, "
            "printf('%.2f', SUM(CASE WHEN lower(direction)='debet' "
            "THEN -amount ELSE 0 END)) AS wydatki, "
            "printf('%.2f', SUM(amount)) AS saldo, "
            "COUNT(*) AS n "
            "FROM transactions_clean "
            "WHERE substr(ym,1,4)=? "
            "GROUP BY ym ORDER BY ym;",
            (year,)
        )
        rows = cur.fetchall()
        return rows
    finally:
        con.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT), help="Ścieżka do SQLite")
    ap.add_argument("--check-june", action="store_true",
                    help="Po utworzeniu widoku pokaż sumę dla 2025-06 (kredyt)")
    ap.add_argument("--year", default=None, help="Pokaż zestawienie dla roku, np. 2025")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERR] Brak bazy: {db_path}", file=sys.stderr)
        sys.exit(1)

    create_view(db_path)
    print("[OK] Utworzono/odświeżono widok transactions_clean")

    if args.check_june:
        s = sum_month(db_path, "2025-06")
        print(f"Suma wpływów (kredyt) 2025-06: {s:.2f}")

    if args.year:
        rows = list_year(db_path, args.year)
        if not rows:
            print(f"(brak danych dla {args.year})")
        else:
            print("ym       | przychody | wydatki | saldo | n")
            for ym, p, w, saldo, n in rows:
                print(f"{ym}|{p}|{w}|{saldo}|{n}")

if __name__ == "__main__":
    main()
