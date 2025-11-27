#!/usr/bin/env python3
import argparse, os, sys, hashlib, sqlite3
from pathlib import Path

DEF_DB = os.path.expanduser("~/.local/share/bankdb/bank.db")
DEF_DIR = os.path.expanduser("~/Inteligo")

def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def pick_canonical(paths):
    # Preferuj nazwę bez " (N).html"
    def score(p: Path):
        name = p.name
        has_dup = "(" in name and ")" in name
        return (has_dup, len(name))
    return sorted(paths, key=score)[0]

def main():
    ap = argparse.ArgumentParser(description="Sync statements_html.saved_path with actual files by sha256")
    ap.add_argument("--db", default=DEF_DB, help="Ścieżka do SQLite (default: %(default)s)")
    ap.add_argument("--dir", default=DEF_DIR, help="Katalog z wyciągami (default: %(default)s)")
    ap.add_argument("--apply", action="store_true", help="Zastosuj zmiany (domyślnie dry-run)")
    ap.add_argument("--delete-dangling", action="store_true", help="Usuń wiersze bez pliku i bez dopasowania sha")
    args = ap.parse_args()

    base = Path(args.dir)
    if not base.is_dir():
        print(f"[ERR] Brak katalogu: {base}", file=sys.stderr); sys.exit(1)

    # 1) Inwentarz plików -> sha256 -> list[path]
    print("[1/4] Skanuję pliki HTML…")
    sha2paths = {}
    files = list(base.glob("*.htm")) + list(base.glob("*.html"))
    for p in files:
        try:
            sha = file_sha256(p)
            sha2paths.setdefault(sha, []).append(p)
        except Exception as e:
            print(f"[WARN] Nie mogę zhashować {p}: {e}", file=sys.stderr)

    # 2) Odczyt DB
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT rowid AS rid, sha256, saved_path FROM statements_html;")
    rows = cur.fetchall()

    # 3) Porównanie i plan zmian
    updates = []
    dangling = []
    ok = 0

    for r in rows:
        rid = r["rid"]
        sha = (r["sha256"] or "").lower()
        saved = Path(r["saved_path"]) if r["saved_path"] else None
        exists = saved and saved.is_file()

        if exists:
            ok += 1
            continue

        # brak pliku na dysku
        if sha and sha in sha2paths:
            target = pick_canonical(sha2paths[sha])
            if not saved or target != saved:
                updates.append((str(target), rid))
        else:
            dangling.append(rid)

    print(f"[2/4] OK (istniejące ścieżki): {ok}")
    print(f"[2/4] Do podmiany saved_path (po sha256): {len(updates)}")
    print(f"[2/4] Bez dopasowania (dangling): {len(dangling)}")

    if not args.apply:
        print("[DRY-RUN] Nie wprowadzam zmian. Dodaj --apply żeby zapisać.")
        return

    # 4) Zastosowanie
    print("[3/4] Aktualizuję saved_path…")
    cur.executemany("UPDATE statements_html SET saved_path=? WHERE rowid=?;", updates)
    print(f"    Zmieniono wierszy: {cur.rowcount if cur.rowcount != -1 else len(updates)}")

    if args.delete_dangling and dangling:
        print("[3/4] Usuwam dangling z DB…")
        q = "DELETE FROM statements_html WHERE rowid IN (%s);" % ",".join("?"*len(dangling))
        cur.execute(q, dangling)
        print(f"    Usunięto wierszy: {cur.rowcount}")

    con.commit()
    print("[4/4] VACUUM…")
    con.execute("VACUUM;")
    con.close()
    print("[OK] Zakończone.")

if __name__ == "__main__":
    main()
