#!/usr/bin/env python3
import os, re, sqlite3, argparse

DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

def norm(s:str) -> str:
    return re.sub(r'\s+', ' ', (s or '').replace('\xa0',' ').strip())

def guess_channel_kind(title:str, direction:str):
    t = title.lower()
    if any(k in t for k in ['blik']):
        return ('blik', 'blik_in' if direction=='kredyt' else 'blik_out')
    if 'karta' in t or 'zakup przy uzyciu karty' in t or 'zakup przy użyciu karty' in t:
        return ('card', 'card_refund' if direction=='kredyt' else 'card_purchase')
    if 'bankomat' in t or 'wypłata z bankomatu' in t or 'wyplata z bankomatu' in t:
        return ('atm', 'atm_deposit' if direction=='kredyt' else 'atm_withdrawal')
    if 'przelew' in t or 'wpływ' in t or 'wplyw' in t:
        return ('transfer', 'incoming_transfer' if direction=='kredyt' else 'outgoing_transfer')
    if 'odsetk' in t:
        return ('interest', 'interest')
    if 'prowizj' in t or 'opłat' in t or 'oplat' in t or 'fee' in t:
        return ('fee', 'fee')
    return (None, 'other')

def extract_party(title:str):
    """Spróbuj znaleźć nazwę kontrahenta.
       1) Jeżeli jest 'Nr ref' → weź fragment tuż PRZED tym markerem, odrzucając oczywiste frazy typu ZAKUP/PRZELEW.
       2) Spróbuj po etykietach 'OD:', 'NADAWCA:', 'ODBIORCA:'.
    """
    if not title: return None
    raw = norm(title)

    # 2) etykiety
    m = re.search(r'(?:ODBIORCA|NADAWCA|OD)\s*:\s*([^\|;]{3,80})', raw, flags=re.I)
    if m:
        cand = norm(m.group(1))
        if 3 <= len(cand) <= 80:
            return cand

    # 1) przed "Nr ref"
    nrpos = re.search(r'\bNr\s*ref', raw, flags=re.I)
    base = raw[:nrpos.start()] if nrpos else raw

    # wytnij typowe frazy systemowe
    base = re.sub(r'ZAKUP PRZY (UŻYCIU|UZYCIU) KARTY', '', base, flags=re.I)
    base = re.sub(r'PRZELEW( PRZYCHODZĄCY| PRZYCHODZCY| WYCHODZĄCY| WYCHODZACY)?', '', base, flags=re.I)
    base = re.sub(r'SYST\.?\s*WPŁYW|SYST\.?\s*WPLYW', '', base, flags=re.I)

    # z końcówki zdania spróbuj wyłuskać "nazwę handlową" (duże litery/cyfry/spacje)
    # bierz 1-3 ostatnie tokeny, które nie wyglądają jak kwota/data
    tokens = [t for t in re.split(r'[|,]|\s{2,}', base) if t.strip()]
    if tokens:
        tail = norm(tokens[-1])
        # odrzuć coś co wygląda na datę/kwotę
        if not re.search(r'\d{2}\.\d{2}\.\d{4}', tail) and not re.search(r'\d+[.,]\d{2}', tail):
            if len(tail) >= 3 and len(tail) <= 60:
                return tail

    # fallback: nic sensownego
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='Zapisz zmiany (domyślnie: podgląd)')
    ap.add_argument('--limit', type=int, default=20000, help='Maks. liczba aktualizacji')
    args = ap.parse_args()

    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # wybierz kandydatów do wzbogacenia
        rows = cur.execute("""
            SELECT id, tx_hash, direction, title, channel, kind, party_name
            FROM transactions_enriched
            WHERE title GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*'
              AND (channel IS NULL OR kind IS NULL OR kind='other' OR party_name IS NULL)
            LIMIT ?;
        """, (args.limit,)).fetchall()

        to_upd = []
        for r in rows:
            title = r['title'] or ''
            direction = (r['direction'] or '').lower()
            ch, kd = guess_channel_kind(title, direction)
            party = extract_party(title)

            new_channel = ch if r['channel'] is None else r['channel']
            new_kind    = kd if (r['kind'] is None or r['kind']=='other') else r['kind']
            new_party   = party if r['party_name'] is None else r['party_name']

            if (new_channel != r['channel']) or (new_kind != r['kind']) or (new_party != r['party_name']):
                to_upd.append((new_channel, new_kind, new_party, r['id']))

        print(f"[PREVIEW] planowanych aktualizacji: {len(to_upd)}")
        for i,(ch,kd,pt,iid) in enumerate(to_upd[:10],1):
            print(f"  #{i:02d} id={iid} -> channel={ch} kind={kd} party={pt}")

        if not args.apply or not to_upd:
            print("[TRYB PODGLĄD] Nic nie zapisano. Dodaj --apply żeby zapisać.")
            return 0

        cur.executemany("""
            UPDATE transactions_enriched
               SET channel = COALESCE(?, channel),
                   kind    = COALESCE(?, kind),
                   party_name = COALESCE(?, party_name)
             WHERE id = ?;
        """, to_upd)
        print(f"[OK] Zaktualizowano {cur.rowcount} wierszy.")

        # podsumowanie po zmianach
        for q, label in [
            ("SELECT channel, COUNT(*) FROM transactions_enriched GROUP BY channel ORDER BY COUNT(*) DESC;",
             "-- channels --"),
            ("SELECT kind, COUNT(*) FROM transactions_enriched GROUP BY kind ORDER BY COUNT(*) DESC;",
             "-- kinds --"),
            ("SELECT COUNT(*) FROM transactions_enriched WHERE party_name IS NOT NULL AND party_name<>'';",
             "-- party_named --"),
        ]:
            print(label)
            for row in cur.execute(q):
                print(*row, sep="|")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
