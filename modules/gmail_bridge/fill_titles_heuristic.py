#!/usr/bin/env python3
import os, re, html, sqlite3, argparse
DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

def html_to_text(src: str) -> str:
    s = re.sub(r'(?is)<script.*?</script>|<style.*?</style>', ' ', src)
    s = re.sub(r'(?is)<[^>]+>', ' ', s)
    s = html.unescape(s).replace('\xa0', ' ')
    s = re.sub(r'[ \t\r\f]+', ' ', s)
    return s

def group_thousands(n: str) -> str:
    # "1967" -> "1 967"
    out, c = [], 0
    for ch in n[::-1]:
        out.append(ch); c += 1
        if c==3:
            c=0
            if len(out) < len(n)+ (len(out)//3): # prymitywne ale wystarczy
                out.append(' ')
    return ''.join(out[::-1]).strip()

def amount_patterns(val: float):
    # generuje możliwe reprezentacje kwoty w HTML (z/bez spacji, z NBSP)
    p = f"{val:.2f}"
    intp, frac = p.split(".")
    pl = f"{intp},{frac}"
    with_sep = f"{group_thousands(intp)},{frac}"
    variants = [
        pl,                                  # 1967,36
        with_sep,                            # 1 967,36
        with_sep.replace(' ', '\u00a0'),     # 1&nbsp;967,36
        p,                                   # 1967.36 (awaryjnie)
    ]
    # dłuższe najpierw (precyzyjniejsze)
    variants = sorted(set(variants), key=len, reverse=True)
    # zamiana kropki na przecinek dla wszystkich wariantów z kropką
    return variants

def resolve_path(cur, hint: str) -> str|None:
    if not hint:
        return None
    if os.path.isabs(hint) and os.path.isfile(hint):
        return hint
    # spróbuj po nazwie pliku w statements_html
    name = os.path.basename(hint)
    row = cur.execute(
        "SELECT saved_path FROM statements_html WHERE saved_path LIKE ? OR filename = ? LIMIT 1;",
        (f"%{name}%", name)
    ).fetchone()
    return row[0] if row else None

def make_title_from_snippet(sn: str) -> str:
    sn = re.sub(r'\s+', ' ', sn).strip()
    # obetnij do rozsądnej długości
    if len(sn) > 160:
        sn = sn[:160] + "…"
    return sn

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ym", help="Pracuj tylko dla danego YYYY-MM (opcjonalnie)")
    ap.add_argument("--limit", type=int, default=50, help="Maks. liczba aktualizacji (domyślnie podgląd 50)")
    ap.add_argument("--apply", action="store_true", help="Zapisz do bazy (domyślnie TYLKO podgląd)")
    args = ap.parse_args()

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        q = """
        SELECT id, tx_hash, ym, op_date, amount, source_hint, title
        FROM transactions_enriched
        WHERE (title IS NULL OR title='' OR title NOT GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*')
        """
        params = []
        if args.ym:
            q += " AND ym = ?"
            params.append(args.ym)
        q += " ORDER BY ym, op_date, id"
        rows = cur.execute(q, params).fetchall()
        if not rows:
            print("[INFO] Brak rekordów do uzupełnienia.")
            return 0

        # cache plików HTML -> tekst
        cache = {}

        upd = []
        for r in rows:
            path = resolve_path(cur, r["source_hint"])
            if not path or not os.path.isfile(path):
                continue
            if path not in cache:
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        cache[path] = html_to_text(f.read())
                except Exception as e:
                    cache[path] = ""
            txt = cache[path]
            if not txt:
                continue

            pats = amount_patterns(abs(float(r["amount"])))
            hit_i = -1
            pat_used = None
            for pat in pats:
                hit_i = txt.find(pat)
                if hit_i >= 0:
                    pat_used = pat
                    break
            if hit_i < 0:
                continue

            # wytnij kontekst koło kwoty
            L = 140
            a = max(0, hit_i - L)
            b = min(len(txt), hit_i + len(pat_used) + L)
            snippet = txt[a:b]

            new_title = make_title_from_snippet(snippet)
            if new_title:
                upd.append((new_title, r["id"], r["tx_hash"], os.path.basename(path)))

            if len(upd) >= args.limit:
                break

        if not upd:
            print("[INFO] Nic nie znaleziono w trybie heurystycznym.")
            return 0

        print("== PODGLĄD propozycji (do", len(upd), ") ==")
        for t, i, h, p in upd[:min(10, len(upd))]:
            print(f"- id={i} file={p} -> '{t}'")

        if args.apply:
            cur.executemany(
                "UPDATE transactions_enriched SET title=? WHERE id=? AND tx_hash=?;",
                [(t,i,h) for (t,i,h,_) in upd]
            )
            con.commit()
            print(f"[OK] Zaktualizowano tytuły: {len(upd)}")
        else:
            print("[TRYB PODGLĄD] Nic nie zapisano. Dodaj --apply żeby zapisać.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
