from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from modules.voice_affordance_reasoner import reason_about_voice_utterance
from modules.voice_device_reasoner import reason_about_device_word

QUESTION_PREFIXES = (
    "co ",
    "co wiesz",
    "kto ",
    "kim jest",
    "czy wiesz",
    "opowiedz",
    "powiedz mi",
    "wyjaśnij",
    "dlaczego",
    "jak działa",
    "jak zrobic",
    "jak zrobić",
)

DEVICE_ACTIONS = (
    "włącz",
    "wlacz",
    "wyłącz",
    "wylacz",
    "zgaś",
    "zgas",
)

DEVICE_TARGETS = (
    "światło",
    "swiatlo",
    "światła",
    "swiatla",
    "lampa",
    "lampę",
    "lampe",
    "led",
    "dioda",
    "diodę",
    "diode",
    "głośnik",
    "glosnik",
    "speaker",
    "shelly",
)

NUMBER_WORDS = {
    "zero": "0",
    "jeden": "1",
    "jedynka": "1",
    "pierwsze": "1",
    "pierwszy": "1",
    "pierwsza": "1",
    "dwa": "2",
    "drugie": "2",
    "drugi": "2",
    "druga": "2",
}

YT_DIRECT_ACTIONS = {
    "pauza": "pause",
    "pause": "pause",
    "wznów": "play_pause",
    "wznow": "play_pause",
    "wznow": "play_pause",
    "play": "play_pause",
    "stop": "pause",
    "następny": "next",
    "nastepny": "next",
    "next": "next",
    "poprzedni": "prev",
    "previous": "prev",
    "skip": "skip",
    "pomiń reklamę": "skip",
    "pomin reklame": "skip",
    "pomiń reklamę na youtube": "skip",
    "fullscreen": "fullscreen",
    "pełny ekran": "fullscreen",
    "pelny ekran": "fullscreen",
    "mute": "mute",
    "wycisz": "mute",
    "unmute": "unmute",
    "odcisz": "unmute",
    "głośniej": "volume_up",
    "glosniej": "volume_up",
    "ciszej": "volume_down",
}

YOUTUBE_PREFIX_RE = re.compile(
    r"^(?:na\s+youtube\s+)?(?:youtube|jutub|yt)\s+(.+)$",
    re.IGNORECASE,
)

YOUTUBE_PLAY_RE = re.compile(
    r"^(?:puść|pusc|odtwórz|odtworz|zagraj|play)\s+(.+)$",
    re.IGNORECASE,
)

STATE_DIR = Path("state")
CONTEXT_PATH = STATE_DIR / "voice_orchestrator_context.json"
YOUTUBE_CONTEXT_TTL_SECONDS = 45
MAX_BARE_MEDIA_QUERY_WORDS = 6
MIN_BARE_MEDIA_QUERY_WORDS = 2
SUSPICIOUS_TOKENS = {"yyy", "eee", "aaa", "hmm", "ymm", "yyyh"}

MEDIA_BAD_TOKENS = {
    "kurwa", "kurwa mać", "kurwa mac",
    "ja pierdole", "o kurwa", "cholera",
    "yyy", "eee", "aaa", "hmm"
}


def looks_like_media_query(text: str) -> bool:
    raw = (text or "").strip()
    low = normalize_text(raw)

    if not low:
        return False

    if low in MEDIA_BAD_TOKENS:
        return False

    words = [w for w in raw.split() if w.strip()]

    if len(words) < 2 or len(words) > 5:
        return False

    weird = 0
    for w in words:
        if not any(c.isalpha() for c in w):
            weird += 1

    if weird > 1:
        return False

    return True


def load_context() -> dict[str, Any]:
    try:
        data = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_context(data: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CONTEXT_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def mark_context(mode: str, text: str, query: str = "") -> None:
    payload = {
        "ts": time.time(),
        "last_mode": mode,
        "last_text": (text or "").strip(),
        "last_query": (query or "").strip(),
    }
    save_context(payload)


def clear_context() -> None:
    save_context({
        "ts": time.time(),
        "last_mode": "none",
        "last_text": "",
        "last_query": "",
    })


def recent_youtube_context() -> bool:
    data = load_context()
    if data.get("last_mode") != "youtube_command":
        return False
    try:
        ts = float(data.get("ts", 0))
    except Exception:
        return False
    return (time.time() - ts) <= YOUTUBE_CONTEXT_TTL_SECONDS


def looks_like_bare_media_query(text: str) -> bool:
    raw = (text or "").strip()
    low = normalize_text(raw)
    if not low:
        return False
    if looks_like_media_query(raw):
        return {
            "mode": "youtube_command",
            "action": "search_play",
            "query": raw,
            "text": raw,
            "confidence": 0.72,
            "reason": "bare_media_query",
        }

    if looks_like_question(raw):
        return False
    if parse_device_command(raw):
        return False
    if parse_youtube_command(raw):
        return False

    words = [w for w in raw.split() if w.strip()]
    if len(words) < MIN_BARE_MEDIA_QUERY_WORDS or len(words) > MAX_BARE_MEDIA_QUERY_WORDS:
        return False

    banned = {
        "włącz", "wlacz", "wyłącz", "wylacz", "zgaś", "zgas",
        "co", "kto", "czy", "jak", "dlaczego", "opowiedz", "powiedz",
    }
    norm_words = [normalize_text(w) for w in words]
    if any(w in banned for w in norm_words):
        return False

    if any(len(w) <= 1 for w in norm_words):
        return False

    if any(w in SUSPICIOUS_TOKENS for w in norm_words):
        return False

    simple_ok = 0
    weird = 0
    for w in norm_words:
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9'\-]*", w):
            simple_ok += 1
        else:
            weird += 1

    if weird > 1:
        return False

    if simple_ok < len(norm_words) - 1:
        return False

    return True

def normalize_text(text: str) -> str:
    raw = (text or "").strip()
    low = raw.lower()
    low = " ".join(low.split())
    return low

def looks_like_question(text: str) -> bool:
    low = normalize_text(text)
    if "?" in (text or ""):
        return True
    return any(low.startswith(prefix) for prefix in QUESTION_PREFIXES)

def parse_device_command(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    low = normalize_text(raw)
    tokens = [normalize_text(t) for t in raw.split() if t.strip()]

    action = None
    if "wyłącz" in low or "wylacz" in low or "zgaś" in low or "zgas" in low:
        action = "off"
    elif "włącz" in low or "wlacz" in low:
        action = "on"

    has_target = any(target in low for target in DEVICE_TARGETS)
    mapped_number = None
    for tok in tokens:
        if tok.isdigit():
            mapped_number = tok
            break
        if tok in NUMBER_WORDS:
            mapped_number = NUMBER_WORDS[tok]
            break

    if not action and has_target and mapped_number in {"1", "2"}:
        action = "on"

    if not action:
        return None

    if not has_target:
        return None

    confidence = 0.95
    if mapped_number is None:
        confidence = 0.80

    normalized_text = raw
    if mapped_number:
        normalized_text = raw + f" [{mapped_number}]"

    return {
        "mode": "device_command",
        "action": action,
        "device_number": mapped_number,
        "text": normalized_text.strip(),
        "confidence": confidence,
    }

def parse_youtube_command(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    low = normalize_text(raw)

    for phrase, action in sorted(YT_DIRECT_ACTIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if low == phrase or low == f"youtube {phrase}" or low == f"yt {phrase}":
            return {
                "mode": "youtube_command",
                "action": action,
                "query": "",
                "text": raw,
                "confidence": 0.98,
            }

    m = YOUTUBE_PLAY_RE.match(raw.strip())
    if m:
        query = m.group(1).strip()
        if query:
            return {
                "mode": "youtube_command",
                "action": "search_play",
                "query": query,
                "text": raw,
                "confidence": 0.97,
            }

    m = YOUTUBE_PREFIX_RE.match(raw.strip())
    if m:
        query = m.group(1).strip()
        if query:
            direct = normalize_text(query)
            direct_action = YT_DIRECT_ACTIONS.get(direct)
            if direct_action:
                return {
                    "mode": "youtube_command",
                    "action": direct_action,
                    "query": "",
                    "text": raw,
                    "confidence": 0.97,
                }
            return {
                "mode": "youtube_command",
                "action": "search_play",
                "query": query,
                "text": raw,
                "confidence": 0.95,
            }

    return None

def detect_mode(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {
            "mode": "unknown",
            "text": "",
            "reason": "empty",
            "confidence": 1.0,
        }

    device = parse_device_command(raw)
    if device:
        device["reason"] = "device_parser_match"
        return device

    youtube = parse_youtube_command(raw)
    if youtube:
        youtube["reason"] = "youtube_parser_match"
        return youtube

    device_reason = reason_about_device_word(raw)
    if device_reason:
        device_reason["text"] = raw
        return device_reason

    affordance = reason_about_voice_utterance(raw)
    if affordance.get("mode") == "propose_action":
        affordance["text"] = raw
        affordance["reason"] = affordance.get("reason") or "affordance_reasoner"
        return affordance

    if looks_like_media_query(raw):
        return {
            "mode": "youtube_command",
            "action": "search_play",
            "query": raw,
            "text": raw,
            "reason": "bare_media_query",
            "confidence": 0.72,
        }

    if looks_like_question(raw):
        return {
            "mode": "knowledge_question",
            "text": raw,
            "reason": "question_pattern",
            "confidence": 0.92,
        }

    if len(raw.split()) >= 3:
        return {
            "mode": "unknown",
            "text": raw,
            "reason": "unclassified_phrase_guard",
            "confidence": 0.40,
        }

    return {
        "mode": "unknown",
        "text": raw,
        "reason": "short_unknown",
        "confidence": 0.60,
    }

def plan_voice_action(text: str) -> dict[str, Any]:
    result = detect_mode(text)
    mode = result.get("mode")

    if mode == "device_command":
        result["dispatch"] = "local_execute"
        mark_context(mode, result.get("text", text))
        return result

    if mode == "youtube_command":
        result["dispatch"] = "local_execute"
        mark_context(mode, result.get("text", text), result.get("query", ""))
        return result

    if mode == "knowledge_question":
        result["dispatch"] = "agent_query"
        clear_context()
        mark_context(mode, result.get("text", text))
        return result

    if mode == "conversation":
        result["dispatch"] = "agent_query"
        clear_context()
        mark_context(mode, result.get("text", text))
        return result

    result["dispatch"] = "ask_repeat"
    return result
