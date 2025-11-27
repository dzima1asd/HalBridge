#!/usr/bin/env python3
import sqlite3, argparse, os, sys
DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

DDL = r"""
CREATE TABLE IF NOT EXISTS transactions_enriched(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ym TEXT,
  op_date TEXT,
  value_date TEXT,
  direction TEXT CHECK(direction IN ('debet','kredyt')),
  amount REAL,
  currency TEXT,
  title TEXT,
  counterparty TEXT,
  source_hint TEXT,
  tx_hash TEXT UNIQUE,
  created_at TEXT,

  -- Pola rozszerzone (na razie puste, będziemy je uzupełniać etapami):
  channel TEXT,            -- 'transfer' | 'card' | 'blik' | 'fee' | ...
  kind TEXT,               -- doprecyzowanie typu (np. 'p2p', 'online', 'atm', 'standing_order' itp.)
  party_role TEXT,         -- 'sender' | 'recipient' (w zależności od direction)
  party_name TEXT,
  party_account TEXT,
  party_phone TEXT,
  merchant TEXT,
  mcc TEXT,
  location TEXT,
  reference_id TEXT,
  note TEXT,
  meta_json TEXT           -- surowe detale, jeśli coś nie pasuje do pól
);
"""

SEED = r"""
INSERT OR IGNORE INTO transactions_enriched
(ym,op_date,value_date,direction,amount,currency,title,counterparty,source_hint,tx_hash,created_at)
SELECT ym,op_date,value_date,direction,amount,currency,title,counterparty,source_hint,tx_hash,created_at
FROM transactions_clean;
"""

SUMMARY = r"""
SELECT 'enriched_rows' AS what, COUNT(*) AS n FROM transactions_enriched
UNION ALL
SELECT 'with_hash', COUNT(tx_hash) FROM transactions_enriched
UNION ALL
SELECT 'year_2025', COUNT(*) FROM transactions_enriched WHERE substr(ym,1,4)='2025';
"""

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--reset", action="store_true", help="DROP + CREATE tabeli transactions_enriched")
  ap.add_argument("--seed", action="store_true", help="Zasiej danymi z widoku transactions_clean")
  ap.add_argument("--summary", action="store_true", help="Pokaż krótkie podsumowanie")
  args = ap.parse_args()

  con = sqlite3.connect(DB)
  con.execute("PRAGMA foreign_keys=ON;")
  cur = con.cursor()

  if args.reset:
    cur.execute("DROP TABLE IF EXISTS transactions_enriched;")
  cur.executescript(DDL)
  con.commit()

  if args.seed:
    cur.executescript(SEED)
    con.commit()

  if args.summary:
    for row in cur.execute(SUMMARY):
      print(f"{row[0]}|{row[1]}")

  con.close()

if __name__ == "__main__":
  main()
