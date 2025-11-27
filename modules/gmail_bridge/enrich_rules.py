#!/usr/bin/env python3
import os, sqlite3

DB = os.path.expanduser("~/.local/share/bankdb/bank.db")

SQL = r"""
-- Ujednolicenie: nie nadpisujemy już ustawionych wartości
-- PART 1: channel

UPDATE transactions_enriched
   SET channel='BLIK'
 WHERE (channel IS NULL OR channel='')
   AND (
         lower(coalesce(title,''))      LIKE '%blik%'
      OR lower(coalesce(counterparty,'')) LIKE '%blik%'
   );

UPDATE transactions_enriched
   SET channel='CARD'
 WHERE (channel IS NULL OR channel='')
   AND (
         lower(coalesce(title,'')) LIKE '%karta%'
      OR lower(coalesce(title,'')) LIKE '%płatno%'
      OR lower(coalesce(title,'')) LIKE '%platno%'
      OR lower(coalesce(title,'')) LIKE '%visa%'
      OR lower(coalesce(title,'')) LIKE '%mastercard%'
      OR lower(coalesce(title,'')) LIKE '%paypass%'
      OR lower(coalesce(title,'')) LIKE '%terminal%'
   );

UPDATE transactions_enriched
   SET channel='TRANSFER'
 WHERE (channel IS NULL OR channel='')
   AND (
         lower(coalesce(title,'')) LIKE '%przelew%'
      OR lower(coalesce(title,'')) LIKE '%elixir%'
      OR lower(coalesce(title,'')) LIKE '%sorbnet%'
      OR lower(coalesce(title,'')) LIKE '%na telefon%'
      OR lower(coalesce(title,'')) LIKE '%p2p%'
      OR lower(coalesce(title,'')) LIKE '%zlecenie sta%'     -- stałe / standing order
      OR lower(coalesce(title,'')) LIKE '%wewnętrzny%' OR lower(coalesce(title,'')) LIKE '%wewnetrzny%'
   );

UPDATE transactions_enriched
   SET channel='CASH'
 WHERE (channel IS NULL OR channel='')
   AND (
         lower(coalesce(title,'')) LIKE '%wpłata gotówk%' OR lower(coalesce(title,'')) LIKE '%wplata gotowk%'
      OR lower(coalesce(title,'')) LIKE '%wpłatomat%'     OR lower(coalesce(title,'')) LIKE '%wplatomat%'
      OR lower(coalesce(title,'')) LIKE '%bankomat%'
   );

-- cokolwiek niezaklasyfikowane do powyższych, a z literami — wrzuć jako 'OTHER'
UPDATE transactions_enriched
   SET channel='OTHER'
 WHERE (channel IS NULL OR channel='')
   AND (coalesce(title,'')<>'' OR coalesce(counterparty,'')<>'')
   AND (coalesce(title,'') GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*'
        OR coalesce(counterparty,'') GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*');

-- PART 2: kind (podtyp)

-- wynagrodzenie / świadczenia
UPDATE transactions_enriched
   SET kind='salary'
 WHERE (kind IS NULL OR kind='')
   AND (
         lower(coalesce(title,'')) LIKE '%wynagrodz%'
      OR lower(coalesce(title,'')) LIKE '%pensj%'
      OR lower(coalesce(title,'')) LIKE '%stypend%'
      OR lower(coalesce(title,'')) LIKE '%zasiłek%' OR lower(coalesce(title,'')) LIKE '%zasilek%'
   )
   AND lower(direction)='kredyt';

-- zwroty / refundacje
UPDATE transactions_enriched
   SET kind='refund'
 WHERE (kind IS NULL OR kind='')
   AND (
         lower(coalesce(title,'')) LIKE '%zwrot%'
      OR lower(coalesce(title,'')) LIKE '%refund%'
      OR lower(coalesce(title,'')) LIKE '%chargeback%'
      OR lower(coalesce(title,'')) LIKE '%korekt%'
   );

-- doładowania (telefon, portfele)
UPDATE transactions_enriched
   SET kind='topup'
 WHERE (kind IS NULL OR kind='')
   AND (
         lower(coalesce(title,'')) LIKE '%doładow%' OR lower(coalesce(title,'')) LIKE '%doladow%'
      OR lower(coalesce(title,'')) LIKE '%top-up%'  OR lower(coalesce(title,'')) LIKE '%topup%'
   );

-- karta: zakupy
UPDATE transactions_enriched
   SET kind='card_purchase'
 WHERE (kind IS NULL OR kind='') AND channel='CARD' AND lower(direction)='debet';

-- karta: zwroty
UPDATE transactions_enriched
   SET kind='card_refund'
 WHERE (kind IS NULL OR kind='') AND channel='CARD' AND lower(direction)='kredyt';

-- blik p2p / przelew na telefon
UPDATE transactions_enriched
   SET kind='p2p'
 WHERE (kind IS NULL OR kind='')
   AND (
         (channel='BLIK')
      OR lower(coalesce(title,'')) LIKE '%na telefon%'
      OR lower(coalesce(title,'')) LIKE '%p2p%'
   );

-- przelewy przychodzące/wychodzące (bez bardziej szczegółowej klasyfikacji powyżej)
UPDATE transactions_enriched
   SET kind='incoming_transfer'
 WHERE (kind IS NULL OR kind='')
   AND channel='TRANSFER' AND lower(direction)='kredyt';

UPDATE transactions_enriched
   SET kind='outgoing_transfer'
 WHERE (kind IS NULL OR kind='')
   AND channel='TRANSFER' AND lower(direction)='debet';

-- wpłata/wypłata gotówki
UPDATE transactions_enriched
   SET kind='cash_deposit'
 WHERE (kind IS NULL OR kind='')
   AND channel='CASH' AND lower(direction)='kredyt';

UPDATE transactions_enriched
   SET kind='cash_withdrawal'
 WHERE (kind IS NULL OR kind='')
   AND channel='CASH' AND lower(direction)='debet';

-- reszta
UPDATE transactions_enriched
   SET kind='other'
 WHERE (kind IS NULL OR kind='')
   AND (coalesce(title,'')<>'' OR coalesce(counterparty,'')<>'');

-- PART 3: party_role + party_name

-- rola
UPDATE transactions_enriched
   SET party_role='sender'
 WHERE (party_role IS NULL OR party_role='')
   AND lower(direction)='kredyt';

UPDATE transactions_enriched
   SET party_role='recipient'
 WHERE (party_role IS NULL OR party_role='')
   AND lower(direction)='debet';

-- nazwa strony: preferuj counterparty, jeśli wygląda na nazwę (zawiera litery)
UPDATE transactions_enriched
   SET party_name=counterparty
 WHERE (party_name IS NULL OR party_name='')
   AND coalesce(counterparty,'') GLOB '*[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]*';

-- (opcjonalnie) proste wzorce z tytułu, np. "Nadawca: XYZ", "Odbiorca: XYZ"
UPDATE transactions_enriched
   SET party_name=trim(substr(title, instr(lower(title),'nadawca:')+9))
 WHERE (party_name IS NULL OR party_name='')
   AND instr(lower(coalesce(title,'')),'nadawca:')>0;

UPDATE transactions_enriched
   SET party_name=trim(substr(title, instr(lower(title),'odbiorca:')+10))
 WHERE (party_name IS NULL OR party_name='')
   AND instr(lower(coalesce(title,'')),'odbiorca:')>0;
"""

def main():
    with sqlite3.connect(DB) as con:
        con.executescript(SQL)
        cur = con.cursor()
        print("== PODSUMOWANIE ==")
        print("-- channels --")
        for row in cur.execute("SELECT coalesce(channel,'(null)'), COUNT(*) FROM transactions_enriched GROUP BY channel ORDER BY 2 DESC;"):
            print(f"{row[0]}|{row[1]}")
        print("-- kinds --")
        for row in cur.execute("SELECT coalesce(kind,'(null)'), COUNT(*) FROM transactions_enriched GROUP BY kind ORDER BY 2 DESC;"):
            print(f"{row[0]}|{row[1]}")
        print("-- party_named --")
        print(cur.execute("SELECT COUNT(*) FROM transactions_enriched WHERE party_name IS NOT NULL AND party_name<>'';").fetchone()[0])

if __name__ == "__main__":
    raise SystemExit(main())

