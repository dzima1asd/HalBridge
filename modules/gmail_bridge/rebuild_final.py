#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
from pathlib import Path

DB_PATH = Path("~/.local/share/bankdb/bank.db").expanduser()

VIEW_SQL = """
DROP VIEW IF EXISTS transactions_clean;
CREATE VIEW transactions_clean AS
SELECT *
FROM transactions_canon
WHERE
  (
    title GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*'
    OR lower(coalesce(title,'')) LIKE '%przelew%'
    OR lower(coalesce(title,'')) LIKE '%płatno%' OR lower(coalesce(title,'')) LIKE '%platno%'
    OR lower(coalesce(title,'')) LIKE '%blik%'
    OR lower(coalesce(title,'')) LIKE '%karta%' OR lower(coalesce(title,'')) LIKE '%operacj%' OR lower(coalesce(title,'')) LIKE '%transakcj%'
    OR lower(coalesce(title,'')) LIKE '%uznanie%' OR lower(coalesce(title,'')) LIKE '%wpływ%' OR lower(coalesce(title,'')) LIKE '%wplyw%' OR lower(coalesce(title,'')) LIKE '%przych%'
  )
  AND NOT (
    lower(coalesce(title,'')) LIKE '%saldo%'
    OR lower(coalesce(title,'')) LIKE '%suma%'
    OR lower(coalesce(title,'')) LIKE '%razem%'
    OR lower(coalesce(title,'')) LIKE '%podsum%'
    OR lower(coalesce(title,'')) LIKE '%ogółem%' OR lower(coalesce(title,'')) LIKE '%ogolem%'
    OR lower(coalesce(title,'')) LIKE '%zestawienie%'
    OR lower(coalesce(title,'')) LIKE '%bilans%'
    OR lower(coalesce(title,'')) LIKE '%przeniesienie%'
    OR lower(coalesce(title,'')) LIKE '%stan konta%'
    OR lower(coalesce(title,'')) LIKE '%dostępne%' OR lower(coalesce(title,'')) LIKE '%dostepne%'
  )
  AND (
       (lower(direction)='kredyt' AND amount > 0)
    OR (lower(direction)='debet'  AND amount < 0)
  )
;
"""

MATERIALIZE_SQL = """
DROP TABLE IF EXISTS transactions_final;
CREATE TABLE transactions_final AS
SELECT *
FROM transactions_clean;

CREATE INDEX IF NOT EXISTS idx_tx_final_ym   ON transactions_final(ym);
CREATE INDEX IF NOT EXISTS idx_tx_final_dir  ON transactions_final(direction);
CREATE INDEX IF NOT EXISTS idx_tx_final_date ON transactions_final(op_date);
"""

CHECK_SQL = """
SELECT ym,
       printf('%.2f', SUM(CASE WHEN lower(direction)='kredyt' THEN amount ELSE 0 END)) AS przychody,
       printf('%.2f', SUM(CASE WHEN lower(direction)='debet'  THEN -amount ELSE 0 END)) AS wydatki,
       printf('%.2f', SUM(amount)) AS saldo,
       COUNT(*) AS n
FROM transactions_final
WHERE substr(ym,1,4)='2025'
GROUP BY ym
ORDER BY ym;
"""

def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # 1) wiele poleceń naraz – używamy executescript
    con.executescript(VIEW_SQL)

    # 2) materializacja do tabeli final
    con.executescript(MATERIALIZE_SQL)
    con.commit()

    # 3) kontrola 2025
    print("ym|przychody|wydatki|saldo|n")
    for row in cur.execute(CHECK_SQL):
        print("|".join(str(x) for x in row))

    # 4) sanity-check: czerwiec i styczeń
    def sum_for(ym, dir_):
        cur.execute(
            "SELECT printf('%.2f', COALESCE(SUM(amount),0)) FROM transactions_final WHERE ym=? AND lower(direction)=?",
            (ym, dir_,),
        )
        return cur.fetchone()[0]

    print("check_2025-06_kredyt=", sum_for("2025-06", "kredyt"))
    print("check_2025-01_kredyt=", sum_for("2025-01", "kredyt"))

    con.close()

if __name__ == "__main__":
    main()

