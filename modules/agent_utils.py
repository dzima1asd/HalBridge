from __future__ import annotations

import json
import urllib.parse


def safe_json(raw, default=None):
    if raw is None:
        return default or {}

    if isinstance(raw, dict):
        return raw

    try:
        return json.loads(str(raw))
    except Exception:
        return default or {}


def urlencode(txt: str) -> str:
    return urllib.parse.quote_plus(txt)
