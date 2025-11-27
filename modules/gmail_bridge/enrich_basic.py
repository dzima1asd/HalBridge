#!/usr/bin/env python3
import os, sqlite3, argparse

DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

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
    ("channel",    "TEXT"),
    ("kind",       "TEXT"),
    ("party_role", "TEXT"),
    ("party_name", "TEXT"),
]

def table_exists(cur, name):
    cur.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?;", (name,))
    return cur.fetchone() is not None

def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table});")
    return any(r[1] == col for r in cur.fetchall())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true",
                    help="wyzeruj kanał/kategorię/stronę (channel/kind/party_*) i zmerguj od nowa")
    args = ap.parse_args()

    with sqlite3.connect(DB) as con:
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys=ON;")

        if not table_exists(cur, "transactions_final"):
            print("ERROR: brak transactions_final — uruchom mk_view_clean.py / rebuild_final.py")
            return 1

        # Struktura enriched
        if not table_exists(cur, "transactions_enriched"):
            cur.executescript(DDL_CREATE)

        for col, typ in ADD_COLS:
            if not col_exists(cur, "transactions_enriched", col):
                cur.execute(f"ALTER TABLE transactions_enriched ADD COLUMN {col} {typ};")

        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_enr_hash ON transactions_enriched(tx_hash);")

        # Opcjonalny reset pól klasyfikacyjnych
        if args.reset:
            cur.execute("UPDATE transactions_enriched SET channel=NULL, kind=NULL, party_role=NULL, party_name=NULL;")

        # INSERT nowych rekordów (po tx_hash)
        before = con.total_changes
        cur.execute("""
            INSERT OR IGNORE INTO transactions_enriched
              (id, ym, op_date, value_date, direction, amount, currency,
               title, counterparty, source_hint, tx_hash, created_at,
               channel, kind, party_role, party_name)
            SELECT
               f.id, f.ym, f.op_date, f.value_date, f.direction, f.amount, f.currency,
               f.title, f.counterparty, f.source_hint, f.tx_hash, f.created_at,
               NULL, NULL, NULL, NULL
            FROM transactions_final f
            WHERE NOT EXISTS (
                SELECT 1 FROM transactions_enriched e WHERE e.tx_hash = f.tx_hash
            );
        """)
        inserted = con.total_changes - before

        # Uzupełnij brakujące tytuły
        before = con.total_changes
        cur.execute("""
            UPDATE transactions_enriched
               SET title = (
                   SELECT f.title FROM transactions_final f
                   WHERE f.tx_hash = transactions_enriched.tx_hash
               )
             WHERE (title IS NULL OR title = '')
               AND tx_hash IN (SELECT tx_hash FROM transactions_final);
        """)
        updated_title = con.total_changes - before

        # Uzupełnij brakującego kontrahenta
        before = con.total_changes
        cur.execute("""
            UPDATE transactions_enriched
               SET counterparty = (
                   SELECT f.counterparty FROM transactions_final f
                   WHERE f.tx_hash = transactions_enriched.tx_hash
               )
             WHERE (counterparty IS NULL OR counterparty = '')
               AND tx_hash IN (SELECT tx_hash FROM transactions_final);
        """)
        updated_counterparty = con.total_changes - before

        con.commit()

        total = cur.execute("SELECT COUNT(*) FROM transactions_enriched;").fetchone()[0]
        party_named = cur.execute(
            "SELECT COUNT(*) FROM transactions_enriched WHERE party_name IS NOT NULL AND party_name<>'';"
        ).fetchone()[0]

        print(f"OK: inserted={inserted} updated_title={updated_title} updated_counterparty={updated_counterparty} total={total} party_named={party_named}")

        print("-- channels --")
        for ch, n in cur.execute("SELECT COALESCE(channel,'(null)'), COUNT(*) FROM transactions_enriched GROUP BY channel ORDER BY COUNT(*) DESC;"):
            print(f"{ch}|{n}")
        print("-- kinds --")
        for k, n in cur.execute("SELECT COALESCE(kind,'(null)'), COUNT(*) FROM transactions_enriched GROUP BY kind ORDER BY COUNT(*) DESC;"):
            print(f"{k}|{n}")

if __name__ == "__main__":
    raise SystemExit(main())
