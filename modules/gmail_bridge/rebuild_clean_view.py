#!/usr/bin/env python3
import sqlite3, os

DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

DDL = r"""
DROP VIEW IF EXISTS transactions_clean;
CREATE VIEW transactions_clean AS
SELECT *
FROM transactions_canon
WHERE
  -- usuń podsumowania/saldo/razem/podsum itp.
  NOT (
    lower(coalesce(title,'')) LIKE '%saldo%'
    OR lower(coalesce(title,'')) LIKE '%suma%'
    OR lower(coalesce(title,'')) LIKE '%razem%'
    OR lower(coalesce(title,'')) LIKE '%podsum%'
    OR lower(coalesce(title,'')) LIKE '%podsumowanie%'
    OR lower(coalesce(title,'')) LIKE '%ogółem%' OR lower(coalesce(title,'')) LIKE '%ogolem%'
    OR lower(coalesce(title,'')) LIKE '%zestawienie%'
    OR lower(coalesce(title,'')) LIKE '%bilans%'
    OR lower(coalesce(title,'')) LIKE '%przeniesienie%'
    OR lower(coalesce(title,'')) LIKE '%stan konta%'
    OR lower(coalesce(title,'')) LIKE '%dostępne%' OR lower(coalesce(title,'')) LIKE '%dostepne%'
  )
  -- usuń fałszywe "kredyty" z tytułem zaczynającym się od minus
  AND NOT (
    lower(direction)='kredyt'
    AND substr(
          replace(replace(coalesce(title,''), ' ', ''), char(160), ''),
          1, 1
        ) IN ('-','−')
  );
"""

def main():
    with sqlite3.connect(DB) as con:
        con.executescript(DDL)
        # szybka kontrola – czerwiec 2025, kredyt
        cur = con.execute("""
          SELECT printf('%.2f', COALESCE(SUM(amount),0))
          FROM transactions_clean
          WHERE ym='2025-06' AND lower(direction)='kredyt';
        """)
        print("clean_june_kredyt=", cur.fetchone()[0])

if __name__ == "__main__":
    main()
