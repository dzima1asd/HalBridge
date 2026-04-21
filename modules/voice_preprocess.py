from __future__ import annotations

import re
import unicodedata
from typing import Any


FILLER_WORDS = {
    "yyy",
    "yy",
    "eeee",
    "eee",
    "hmm",
    "mmm",
    "aha",
    "no",
}

EXACT_NORMALIZATIONS = {
    "jutub": "youtube",
    "you tube": "youtube",
    "you tuba": "youtube",
    "swiatlo": "światło",
    "swiatła": "światła",
    "wlacz": "włącz",
    "wlacz światlo": "włącz światło",
    "wylacz": "wyłącz",
    "wylacz światlo": "wyłącz światło",
    "zgas swiatlo": "zgaś światło",
    "hal": "hal",
    "chal": "hal",
    "kal": "hal",
}

TOKEN_NORMALIZATIONS = {
    "jutub": "youtube",
    "youtubee": "youtube",
    "you": "you",
    "tube": "tube",
    "swiatlo": "światło",
    "swiatla": "światła",
    "wlacz": "włącz",
    "wylacz": "wyłącz",
    "zgas": "zgaś",
    "lampe": "lampę",
    "halu": "hal",
    "chal": "hal",
    "kal": "hal",
}


YOUTUBE_PREFIX_PATTERNS = (
    "włącz youtube ",
    "wlacz youtube ",
    "youtube ",
    "yt ",
    "odtwórz youtube ",
    "odtworz youtube ",
    "odtwórz na youtube ",
    "odtworz na youtube ",
    "puść youtube ",
    "pusc youtube ",
    "puść na youtube ",
    "pusc na youtube ",
)

YOUTUBE_QUERY_EXACT = {
    "motor hed": "motorhead",
    "motor hed": "motorhead",
    "moterhed": "motorhead",
    "moter head": "motorhead",
    "moto head": "motorhead",
    "metalika": "metallica",
    "mettalica": "metallica",
    "ajron mejden": "iron maiden",
    "iron mejden": "iron maiden",
    "blek sabat": "black sabbath",
    "blek sabbath": "black sabbath",
    "esi disi": "ac dc",
    "ej si di si": "ac dc",
    "acdc": "ac dc",
    "of spring": "offspring",
}

YOUTUBE_QUERY_EXACT_EXTRA = {
    "motorhead": "motorhead",
    "motor hed": "motorhead",
    "motor head": "motorhead",
    "moterhed": "motorhead",
    "moter head": "motorhead",
    "metallica": "metallica",
    "metalika": "metallica",
    "iron maiden": "iron maiden",
    "ajron mejden": "iron maiden",
    "black sabbath": "black sabbath",
    "blek sabat": "black sabbath",
    "ac dc": "ac dc",
    "acdc": "ac dc",
    "esi disi": "ac dc",
    "offspring": "offspring",
    "offspring": "offspring",
    "nirvana": "nirvana",
    "slayer": "slayer",
    "megadeth": "megadeth",
    "guns n roses": "guns n roses",
    "ganz en rouzis": "guns n roses",
    "deep purple": "deep purple",
    "dip pörpl": "deep purple",
    "led zeppelin": "led zeppelin",
    "red hot chili peppers": "red hot chili peppers",
    "radiohead": "radiohead",
    "rammstein": "rammstein",
    "queen": "queen",
    "the prodigy": "the prodigy",
    "prodigy": "the prodigy",
}

YOUTUBE_QUERY_TOKEN_MAP = {
    "moterhed": "motorhead",
    "moterhead": "motorhead",
    "metalika": "metallica",
    "mejden": "maiden",
    "ajron": "iron",
    "blek": "black",
    "sabat": "sabbath",
    "esi": "ac",
    "disi": "dc",
    "acdc": "ac dc",
}


YOUTUBE_PREFIX_PATTERNS = (
    "włącz youtube ",
    "wlacz youtube ",
    "youtube ",
    "yt ",
    "odtwórz youtube ",
    "odtworz youtube ",
    "odtwórz na youtube ",
    "odtworz na youtube ",
    "puść youtube ",
    "pusc youtube ",
    "puść na youtube ",
    "pusc na youtube ",
)

YOUTUBE_QUERY_EXACT = {
    "motor hed": "motorhead",
    "motor hed": "motorhead",
    "moterhed": "motorhead",
    "moter head": "motorhead",
    "moto head": "motorhead",
    "metalika": "metallica",
    "mettalica": "metallica",
    "ajron mejden": "iron maiden",
    "iron mejden": "iron maiden",
    "blek sabat": "black sabbath",
    "blek sabbath": "black sabbath",
    "esi disi": "ac dc",
    "ej si di si": "ac dc",
    "acdc": "ac dc",
    "of spring": "offspring",
}

YOUTUBE_QUERY_TOKEN_MAP = {
    "moterhed": "motorhead",
    "moterhead": "motorhead",
    "metalika": "metallica",
    "mejden": "maiden",
    "ajron": "iron",
    "blek": "black",
    "sabat": "sabbath",
    "esi": "ac",
    "disi": "dc",
    "acdc": "ac dc",
}

NUMBER_WORDS = {
    "jeden": "1",
    "jedna": "1",
    "pierwsze": "1",
    "pierwszy": "1",
    "dwa": "2",
    "drugie": "2",
    "drugi": "2",
}


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _cleanup_spacing(text: str) -> str:
    text = re.sub(r"[„”\"'`]+", " ", text)
    text = re.sub(r"[,;:]+", " ", text)
    text = re.sub(r"[!?]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_tokens(text: str) -> str:
    tokens = text.split()
    out: list[str] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i].lower()

        if i + 1 < len(tokens) and tok == "you" and tokens[i + 1].lower() == "tube":
            out.append("youtube")
            i += 2
            continue

        mapped = TOKEN_NORMALIZATIONS.get(tok, tok)
        mapped = NUMBER_WORDS.get(mapped, mapped)
        out.append(mapped)
        i += 1

    return " ".join(out).strip()



def _normalize_youtube_query(text: str) -> str:
    low = text.lower().strip()
    prefix_used = None
    for prefix in YOUTUBE_PREFIX_PATTERNS:
        if low.startswith(prefix):
            prefix_used = prefix
            break

    if prefix_used is None:
        return text

    query = text[len(prefix_used):].strip()
    if not query:
        return text

    query_low = query.lower().strip()
    if query_low in YOUTUBE_QUERY_EXACT:
        return (prefix_used + YOUTUBE_QUERY_EXACT[query_low]).strip()

    if query_low in YOUTUBE_QUERY_EXACT_EXTRA:
        return (prefix_used + YOUTUBE_QUERY_EXACT_EXTRA[query_low]).strip()

    out = []
    for tok in query_low.split():
        mapped = YOUTUBE_QUERY_TOKEN_MAP.get(tok, tok)
        out.extend(mapped.split())
    query_norm = " ".join(out).strip()

    if not query_norm:
        return text

    return (prefix_used + query_norm).strip()



def _normalize_youtube_query(text: str) -> str:
    low = text.lower().strip()
    prefix_used = None
    for prefix in YOUTUBE_PREFIX_PATTERNS:
        if low.startswith(prefix):
            prefix_used = prefix
            break

    if prefix_used is None:
        return text

    query = text[len(prefix_used):].strip()
    if not query:
        return text

    query_low = query.lower().strip()
    if query_low in YOUTUBE_QUERY_EXACT:
        return (prefix_used + YOUTUBE_QUERY_EXACT[query_low]).strip()

    out = []
    for tok in query_low.split():
        mapped = YOUTUBE_QUERY_TOKEN_MAP.get(tok, tok)
        out.extend(mapped.split())
    query_norm = " ".join(out).strip()

    if not query_norm:
        return text

    return (prefix_used + query_norm).strip()


def _remove_leading_fillers(text: str) -> str:
    tokens = text.split()
    while tokens and tokens[0].lower() in FILLER_WORDS:
        tokens.pop(0)
    return " ".join(tokens).strip()


def preprocess_voice_text(text: str) -> dict[str, Any]:
    raw = (text or "").strip()

    if not raw:
        return {
            "ok": False,
            "raw": "",
            "text": "",
            "low": "",
            "ascii_low": "",
            "tokens": [],
            "changed": False,
            "reason": "empty",
        }

    cleaned = _cleanup_spacing(raw)
    low = cleaned.lower()
    ascii_low = _strip_accents(low)

    if ascii_low in EXACT_NORMALIZATIONS:
        cleaned = EXACT_NORMALIZATIONS[ascii_low]
        low = cleaned.lower()
        ascii_low = _strip_accents(low)

    normalized = _normalize_tokens(cleaned)
    normalized = _remove_leading_fillers(normalized)
    normalized = _cleanup_spacing(normalized)
    normalized = _normalize_youtube_query(normalized)
    normalized = _cleanup_spacing(normalized)
    normalized = _normalize_youtube_query(normalized)
    normalized = _cleanup_spacing(normalized)

    if not normalized:
        return {
            "ok": False,
            "raw": raw,
            "text": "",
            "low": "",
            "ascii_low": "",
            "tokens": [],
            "changed": True,
            "reason": "empty_after_cleanup",
        }

    low = normalized.lower()
    ascii_low = _strip_accents(low)
    tokens = normalized.split()

    if len(low) < 2:
        return {
            "ok": False,
            "raw": raw,
            "text": normalized,
            "low": low,
            "ascii_low": ascii_low,
            "tokens": tokens,
            "changed": normalized != raw,
            "reason": "too_short",
        }

    if len(tokens) == 1 and low in FILLER_WORDS:
        return {
            "ok": False,
            "raw": raw,
            "text": normalized,
            "low": low,
            "ascii_low": ascii_low,
            "tokens": tokens,
            "changed": normalized != raw,
            "reason": "filler_only",
        }

    if re.fullmatch(r"[a-zA-Ząćęłńóśźż]+", low) and len(low) <= 2:
        return {
            "ok": False,
            "raw": raw,
            "text": normalized,
            "low": low,
            "ascii_low": ascii_low,
            "tokens": tokens,
            "changed": normalized != raw,
            "reason": "tiny_token",
        }

    return {
        "ok": True,
        "raw": raw,
        "text": normalized,
        "low": low,
        "ascii_low": ascii_low,
        "tokens": tokens,
        "changed": normalized != raw,
        "reason": "ok",
    }


if __name__ == "__main__":
    raise SystemExit("voice_preprocess.py is a module, not a standalone runner")
