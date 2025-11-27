#!/usr/bin/env python3
import os, re, shutil, hashlib, sqlite3, time
from pathlib import Path
DIR = Path(os.path.expanduser("~/Inteligo"))
ARCH = DIR / f"archive_dupes_{time.strftime('%Y%m%d_%H%M%S')}"
DB  = os.path.expanduser("~/.local/share/bankdb/bank.db")

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def is_html(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in (".html", ".htm")

def base_pref_key(p: Path) -> tuple:
    # prefer name BEZ " (N).html", a potem krótsza nazwa
    m = re.search(r"\s\(\d+\)$", p.stem)
    has_copy = 1 if m else 0
    return (has_copy, len(p.name), p.name)

def main():
    files = [p for p in DIR.iterdir() if is_html(p)]
    if not files:
        print("Brak plików HTML w ~/Inteligo.")
        return

    # Zgrupuj po SHA256
    by_hash = {}
    print("Liczenie SHA256...")
    for p in files:
        try:
            d = sha256(p)
            by_hash.setdefault(d, []).append(p)
        except Exception as e:
            print(f"[WARN] Pomijam {p}: {e}")

    to_move = []  # (src, dst, sha256)
    kept = []
    ARCH.mkdir(parents=True, exist_ok=True)

    for d, plist in by_hash.items():
        if len(plist) == 1:
            kept.append(plist[0])
            continue
        # wybierz główny
        plist_sorted = sorted(plist, key=base_pref_key)
        keep = plist_sorted[0]
        kept.append(keep)
        # reszta do archiwum
        for q in plist_sorted[1:]:
            dst = ARCH / q.name
            i = 1
            while dst.exists():
                dst = ARCH / f"{q.stem} ({i}){q.suffix}"
                i += 1
            to_move.append((q, dst, d))

    # Przenieś duplikaty
    moved = []
    for src, dst, d in to_move:
        try:
            shutil.move(str(src), str(dst))
            moved.append((src, dst, d))
        except Exception as e:
            print(f"[WARN] Nie przeniosłem {src}: {e}")

    # Zaktualizuj SQLite dla przeniesionych (po sha256 i starej ścieżce)
    updated = 0
    if moved:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        for src, dst, d in moved:
            cur.execute(
                """UPDATE statements_html
                   SET saved_path=?, filename=?
                   WHERE sha256=? AND saved_path=?""",
                (str(dst), dst.name, d, str(src))
            )
            updated += cur.rowcount
        con.commit()
        con.close()

    print("== PODSUMOWANIE ==")
    print(f"Plików HTML ogółem: {len(files)}")
    print(f"Unikatowych hashy:  {len(by_hash)}")
    print(f"Zachowanych (głównych): {len(kept)}")
    print(f"Przeniesionych duplikatów: {len(moved)} -> {ARCH}")
    print(f"Zaktualizowanych wierszy w statements_html: {updated}")

if __name__ == "__main__":
    main()
