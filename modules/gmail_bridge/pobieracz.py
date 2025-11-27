#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pobieracz.py — zgrywa wyciągi okresowe (HTML) z Gmaila dla Inteligo/PKO i rejestruje je w SQLite.

Co potrafi:
- Logowanie do Gmail API (readonly).
- Wyszukiwanie wiadomości (domyślnie: wszystkie z ZAŁĄCZNIKAMI od inteligo/pkobp, szeroki zakres dat).
- Pobieranie ZAŁĄCZNIKÓW .html/.htm (rekurencyjnie po częściach MIME).
- Filtrowanie „czy to na pewno wyciąg” (można wyłączyć przełącznikiem).
- Zapis do ~/Inteligo z unikalnymi nazwami.
- Rejestr w SQLite: ~/.local/share/bankdb/bank.db, tabela statements_html.

Przykłady:
  python3 pobieracz.py
  python3 pobieracz.py --dest ~/Inteligo --all-html --no-sender-filter
  python3 pobieracz.py --query '(has:attachment filename:(html OR htm)) subject:"wyciąg okresowy" after:2000/01/01 before:2030/01/01' --no-sender-filter
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List, Tuple

from googleapiclient.discovery import build  # type: ignore
from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore

# =========================
# Stałe i konfiguracja
# =========================

CONF_DIR = Path("~/.config/gmail_bridge").expanduser()
CREDS_JSON = CONF_DIR / "client_secret.json"
TOKEN_JSON = CONF_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

ALLOWED_SENDER_DOMAINS = ("inteligo.pl", "pkobp.pl")

DB_PATH = Path("~/.local/share/bankdb/bank.db").expanduser()
DDL = """
CREATE TABLE IF NOT EXISTS statements_html(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  gmail_id TEXT NOT NULL,
  attachment_id TEXT NOT NULL,
  message_ts_ms INTEGER,
  date_iso TEXT,
  month TEXT,
  subject TEXT,
  sender TEXT,
  filename TEXT,
  saved_path TEXT,
  sha256 TEXT,
  mime_type TEXT,
  size_bytes INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(gmail_id, attachment_id)
);
CREATE INDEX IF NOT EXISTS idx_statements_month ON statements_html(month);
CREATE INDEX IF NOT EXISTS idx_statements_sha   ON statements_html(sha256);
"""

# =========================
# Pomocnicze
# =========================

def sender_domain_ok(addr: str) -> bool:
    dom = (addr.split("@")[-1] or "").lower()
    return any(dom.endswith(d) for d in ALLOWED_SENDER_DOMAINS)

def sanitize_filename(s: str) -> str:
    s = (s or "").strip().replace("\u00A0", " ")
    return re.sub(r'[\\/:*?"<>|\n\r\t]', "_", s) or "statement.html"

def save_unique(dest_dir: Path, base_name: str, content: bytes) -> Path:
    name = sanitize_filename(base_name)
    target = dest_dir / name
    stem, suffix = target.stem, (target.suffix or ".html")
    i = 1
    while target.exists():
        target = dest_dir / f"{stem} ({i}){suffix}"
        i += 1
    target.write_bytes(content)
    return target

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def ts_ms_to_iso(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0, datetime.UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def month_from_ts(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000.0)
    return dt.strftime("%Y-%m")

def looks_like_statement(subject: str, filename: str, content: bytes) -> bool:
    """
    Heurystyka: nazwa/temat/treść zawiera:
    - 'wyciąg okresowy' lub 'wyciag okresowy'
    - lub nazwę pliku w stylu 'wyciag_*.html' albo 'Historia_Rachunku*.html'
    - albo w treści słowa 'wyciąg/wyciag/zestawienie' + 'okres'
    """
    subj = (subject or "").lower()
    name = (filename or "").lower()
    if "wyciąg okresowy" in subj or "wyciag okresowy" in subj:
        return True
    if name.startswith(("wyciag_", "wyciąg_", "historia_rachunku")):
        return True
    if any(k in name for k in ("wyciąg", "wyciag", "zestawienie")):
        return True
    try:
        txt = content.decode("utf-8", "ignore").lower()
    except Exception:
        return False
    hits = sum(1 for k in ("wyciąg", "wyciag", "zestawienie") if k in txt)
    return bool(hits and ("okres" in txt or "za okres" in txt))

# =========================
# SQLite
# =========================

def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(DDL)

def insert_row(row: Dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """INSERT OR IGNORE INTO statements_html
               (gmail_id, attachment_id, message_ts_ms, date_iso, month, subject, sender,
                filename, saved_path, sha256, mime_type, size_bytes)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["gmail_id"],
                row["attachment_id"],
                row["message_ts_ms"],
                row["date_iso"],
                row["month"],
                row["subject"],
                row["sender"],
                row["filename"],
                row["saved_path"],
                row["sha256"],
                row["mime_type"],
                row["size_bytes"],
            ),
        )
        con.commit()

# =========================
# Gmail API
# =========================

def load_service():
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    creds: Credentials | None = None
    if TOKEN_JSON.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_JSON), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_JSON.exists():
                print("@#@Brak pliku client_secret.json w ~/.config/gmail_bridge@#@")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_JSON), SCOPES)
            creds = flow.run_console()
            TOKEN_JSON.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def gmail_list_all_ids(svc, query: str, max_per_page: int = 500) -> List[str]:
    ids: List[str] = []
    token = None
    while True:
        res = (
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_per_page, pageToken=token)
            .execute()
        )
        for it in res.get("messages", []) or []:
            ids.append(it["id"])
        token = res.get("nextPageToken")
        if not token:
            break
    return ids

def gmail_get_message(svc, mid: str) -> Dict[str, Any]:
    return svc.users().messages().get(userId="me", id=mid, format="full").execute()

def gmail_get_attachment(svc, mid: str, att_id: str) -> bytes:
    data = (
        svc.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=mid, id=att_id)
        .execute()
    )
    return base64.urlsafe_b64decode(data["data"])

# =========================
# Zbieranie załączników HTML
# =========================

def _walk_parts_collect(parts: List[Dict[str, Any]], acc: List[Tuple[str, str, str, int]]) -> None:
    for p in parts or []:
        fn = p.get("filename") or ""
        mt = (p.get("mimeType") or "").lower()
        body = p.get("body") or {}
        att_id = body.get("attachmentId")
        size = int(body.get("size", 0)) if "size" in body else 0
        if att_id and (fn.lower().endswith((".html", ".htm")) or mt == "text/html"):
            acc.append((fn or "statement.html", mt or "text/html", att_id, size))
        _walk_parts_collect(p.get("parts") or [], acc)

def collect_html_attachments(msg: Dict[str, Any]) -> List[Tuple[str, str, str, int]]:
    attachments: List[Tuple[str, str, str, int]] = []
    payload = msg.get("payload", {}) or {}

    fn_top = payload.get("filename") or ""
    mt_top = (payload.get("mimeType") or "").lower()
    body_top = payload.get("body") or {}
    att_top = body_top.get("attachmentId")
    size_top = int(body_top.get("size", 0)) if "size" in body_top else 0

    if att_top and (fn_top.lower().endswith((".html", ".htm")) or mt_top == "text/html"):
        attachments.append((fn_top or "statement.html", mt_top or "text/html", att_top, size_top))

    _walk_parts_collect(payload.get("parts") or [], attachments)
    return attachments

# =========================
# CLI
# =========================

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Pobieranie wyciągów (HTML) z Gmaila dla Inteligo/PKO i rejestr do SQLite."
    )
    p.add_argument(
        "--dest",
        default=str(Path("~/Inteligo").expanduser()),
        help="Folder docelowy (domyślnie: ~/Inteligo)",
    )
    p.add_argument(
        "--query",
        default='(has:attachment filename:(html OR htm)) (from:inteligo@inteligo.pl OR from:inteligo.pl OR from:pkobp.pl) after:2000/01/01 before:2030/01/01',
        help="Kwerenda Gmail (domyślnie: wszystkie maile z załącznikami od banku, szerokie daty)",
    )
    p.add_argument(
        "--all-html",
        action="store_true",
        help="Zapisuj każdy załącznik HTML (wyłącza filtr wyciągów).",
    )
    p.add_argument(
        "--no-sender-filter",
        action="store_true",
        help="Nie filtruj po domenie nadawcy (przydatne dla forwardów typu 'Fwd: ...').",
    )
    return p

# =========================
# Główna logika
# =========================

def main() -> None:
    args = build_argparser().parse_args()
    dest_dir = Path(args.dest).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)

    ensure_db()
    svc = load_service()

    ids = gmail_list_all_ids(svc, args.query, max_per_page=500)

    saved, skipped = 0, 0
    for mid in ids:
        try:
            msg = gmail_get_message(svc, mid)
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subj = headers.get("subject", "")
            sender_hdr = headers.get("from", "")
            from_addr = parseaddr(sender_hdr)[1].lower()

            if not args.no_sender_filter and not sender_domain_ok(from_addr):
                continue

            att_list = collect_html_attachments(msg)
            if not att_list:
                continue

            ts_ms = int(msg.get("internalDate", "0"))
            date_iso = ts_ms_to_iso(ts_ms)
            month = month_from_ts(ts_ms)
            subj_stub = sanitize_filename(subj)[:60] or "statement"

            for (filename, mimeType, att_id, size_bytes) in att_list:
                content = gmail_get_attachment(svc, mid, att_id)
                if not args.all_html and not looks_like_statement(subj, filename, content):
                    continue

                h = sha256_bytes(content)
                base_name = f"{month} - {subj_stub} - {filename or 'statement.html'}"
                path = save_unique(dest_dir, base_name, content)

                insert_row(
                    {
                        "gmail_id": mid,
                        "attachment_id": att_id,
                        "message_ts_ms": ts_ms,
                        "date_iso": date_iso,
                        "month": month,
                        "subject": subj,
                        "sender": sender_hdr,
                        "filename": path.name,
                        "saved_path": str(path),
                        "sha256": h,
                        "mime_type": mimeType,
                        "size_bytes": len(content) if content is not None else size_bytes,
                    }
                )
                saved += 1

        except Exception as e:
            print(f"Błąd wiadomości {mid}: {e}")
            skipped += 1

    print("@#@MODEL_BAZA@#@")
    print(json.dumps({"db_path": str(DB_PATH), "table": "statements_html"}, ensure_ascii=False, indent=2))
    print("@#@PODSUMOWANIE@#@")
    print(f"Zapisano plików: {saved}, pominięto: {skipped}, katalog: {dest_dir}")
    print("@#@KONIEC@#@")

if __name__ == "__main__":
    main()
