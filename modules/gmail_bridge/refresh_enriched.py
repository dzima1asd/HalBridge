#!/usr/bin/env python3
import os, sqlite3, argparse

DEFAULT_DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

DDL_CREATE = """
CREATE TABLE transactions_enriched AS
SELECT
  id, ym, op_date, value_date, direction, amount, currency,
  title, counterparty, source_hint, tx_hash, created_at,
  CAST(NULL AS TEXT) AS channel,
  CAST(NULL AS TEXT) AS kind,
  CAST(NULL AS TEXT) AS party_role,
  CAST(NULL AS TEXT) AS party_name
FROM transactions_final
WHERE 0;
"""

ADD_COLS = [
    ("channel","TEXT"),("kind","TEXT"),
    ("party_role","TEXT"),("party_name","TEXT"),
]

def table_exists(cur, name):
    cur.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?;", (name,))
    return cur.fetchone() is not None

def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table});")
    return any(r[1]==col for r in cur.fetchall())

def ensure_schema(con, reset=False):
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=ON;")
    if not table_exists(cur, "transactions_final"):
        raise SystemExit("Brak transactions_final — uruchom najpierw mk_view_clean.py / rebuild_final.py")
    if reset and table_exists(cur, "transactions_enriched"):
        cur.execute("DROP TABLE IF EXISTS transactions_enriched;")
    if not table_exists(cur, "transactions_enriched"):
        cur.executescript(DDL_CREATE)
    for col, typ in ADD_COLS:
        if not col_exists(cur, "transactions_enriched", col):
            cur.execute(f"ALTER TABLE transactions_enriched ADD COLUMN {col} {typ};")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_enr_hash ON transactions_enriched(tx_hash);")

def merge_from_final(con):
    cur = con.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO transactions_enriched
        (id, ym, op_date, value_date, direction, amount, currency,
         title, counterparty, source_hint, tx_hash, created_at,
         channel, kind, party_role, party_name)
        SELECT f.id, f.ym, f.op_date, f.value_date, f.direction, f.amount, f.currency,
               f.title, f.counterparty, f.source_hint, f.tx_hash, f.created_at,
               NULL, NULL, NULL, NULL
        FROM transactions_final f
        LEFT JOIN transactions_enriched e ON e.tx_hash=f.tx_hash
        WHERE e.tx_hash IS NULL;
    """)
    inserted = cur.rowcount or 0
    cur.execute("""
        UPDATE transactions_enriched
           SET title=(SELECT f.title FROM transactions_final f WHERE f.tx_hash=transactions_enriched.tx_hash)
         WHERE (title IS NULL OR title='')
           AND tx_hash IN (SELECT tx_hash FROM transactions_final);
    """)
    upd_title = cur.rowcount or 0
    cur.execute("""
        UPDATE transactions_enriched
           SET counterparty=(SELECT f.counterparty FROM transactions_final f WHERE f.tx_hash=transactions_enriched.tx_hash)
         WHERE (counterparty IS NULL OR counterparty='')
           AND tx_hash IN (SELECT tx_hash FROM transactions_final);
    """)
    upd_cp = cur.rowcount or 0
    return inserted, upd_title+upd_cp

def summarize(con):
    cur = con.cursor()
    total   = cur.execute("SELECT COUNT(*) FROM transactions_enriched;").fetchone()[0]
    kinds   = cur.execute("SELECT kind, COUNT(*) FROM transactions_enriched GROUP BY kind ORDER BY COUNT(*) DESC;").fetchall()
    chans   = cur.execute("SELECT channel, COUNT(*) FROM transactions_enriched GROUP BY channel ORDER BY COUNT(*) DESC;").fetchall()
    named   = cur.execute("SELECT COUNT(*) FROM transactions_enriched WHERE party_name IS NOT NULL AND party_name<>'';").fetchone()[0]
    print("== PODSUMOWANIE ==")
    print("-- rows_enriched --"); print(total)
    print("-- channels --");      [print(f"{c}|{n}") for c,n in chans]
    print("-- kinds --");         [print(f"{k}|{n}") for k,n in kinds]
    print("-- party_named --");   print(named)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    with sqlite3.connect(os.path.expanduser(args.db)) as con:
        con.execute("BEGIN IMMEDIATE;")
        ensure_schema(con, reset=args.reset)
        ins, upd = merge_from_final(con)
        con.commit()
        print(f"OK: inserted={ins}, updated={upd}")
        summarize(con)

if __name__ == "__main__":
    main()
