from __future__ import annotations

import tempfile
import unicodedata
import wave
from pathlib import Path
from typing import Any

from modules.voice_stt import transcribe_wav


YOUTUBE_PREFIXES = [
    "włącz youtube",
    "wlacz youtube",
    "uruchom youtube",
    "odpal youtube",
    "otwórz youtube",
    "otworz youtube",
    "puść youtube",
    "pusc youtube",
    "play youtube",
    "youtube",
    "yt",
    "play",
    "puść",
    "pusc",
    "odtwórz",
    "odtworz",
]

EN_PREFIX_MARKERS = (
    "turn on youtube ",
    "open youtube ",
    "start youtube ",
    "play youtube ",
    "youtube ",
    "play ",
    "yt ",
)

NOISE_PREFIXES = (
    "want you to ",
    "won't you ",
    "wont you ",
    "want to ",
    "here to ",
    "here top ",
    "here too ",
    "you to ",
    "on youtube ",
    "the youtube ",
)

COMMAND_WORDS = {
    "youtube",
    "yt",
    "play",
    "turn",
    "open",
    "start",
    "on",
    "włącz",
    "wlacz",
    "puść",
    "pusc",
    "odtwórz",
    "odtworz",
    "uruchom",
    "odpal",
    "otwórz",
    "otworz",
}

FILLER_WORDS = {
    "the",
    "a",
    "an",
    "to",
    "for",
    "me",
    "mi",
    "na",
    "you",
    "want",
    "here",
    "too",
    "watch",
}

COMMAND_ONLY_PATTERNS = {
    "youtube",
    "yt",
    "watch you youtube",
    "watch youtube",
    "play youtube",
    "open youtube",
    "start youtube",
    "turn on youtube",
}

QUERY_REPLACEMENTS = {
    "motor had": "motorhead",
    "motor head": "motorhead",
    "moterhead": "motorhead",
    "moter head": "motorhead",
    "the dors": "the doors",
    "doors band": "the doors",
    "off spring": "offspring",
    "of spring": "offspring",
    "nirvanna": "nirvana",
    "iron maidenz": "iron maiden",
    "meta lica": "metallica",
    "gun zyn roses": "guns n roses",
    "guns and roses": "guns n roses",
    "assy dc": "ac dc",
    "acdc": "ac dc",
}


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(ch)
    )


def _norm_token(text: str) -> str:
    raw = _strip_accents((text or "").lower())
    cleaned = []
    for ch in raw:
        cleaned.append(ch if (ch.isalnum() or ch in {"'", "+"}) else " ")
    return " ".join("".join(cleaned).split())


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _norm_token(text).split() if tok]


def _strip_known_en_prefix(text: str) -> str:
    raw = " ".join((text or "").strip().split())
    low = raw.lower()

    for marker in EN_PREFIX_MARKERS:
        if low.startswith(marker):
            return raw[len(marker):].strip()

    return raw.strip()


def _cleanup_music_query(text: str) -> str:
    raw = " ".join((text or "").strip().split())
    low = raw.lower()

    for prefix in NOISE_PREFIXES:
        if low.startswith(prefix):
            raw = raw[len(prefix):].strip()
            low = raw.lower()
            break

    raw = _strip_known_en_prefix(raw)
    low = raw.lower()

    for bad, good in QUERY_REPLACEMENTS.items():
        if low == bad:
            return good
        if low.startswith(bad + " "):
            return (good + raw[len(bad):]).strip()

    return raw.strip()


def _looks_like_command_only(text: str) -> bool:
    q = _norm_token(_cleanup_music_query(text))
    if not q:
        return True
    if q in COMMAND_ONLY_PATTERNS:
        return True
    toks = [t for t in q.split() if t]
    if toks and all(t in COMMAND_WORDS or t in FILLER_WORDS for t in toks):
        return True
    return False


def _music_query_score(text: str) -> float:
    q = _cleanup_music_query(_strip_known_en_prefix(text))
    if not q:
        return -100.0

    if _looks_like_command_only(q):
        return -80.0

    tokens = _tokenize(q)
    if not tokens:
        return -100.0

    score = 0.0
    score += min(len(q), 24) * 0.08
    score += min(len(tokens), 5) * 1.2

    if 1 <= len(tokens) <= 6:
        score += 2.0
    elif len(tokens) > 8:
        score -= 2.5

    ascii_letters = sum(1 for ch in q if ch.isascii() and ch.isalpha())
    total_letters = sum(1 for ch in q if ch.isalpha())
    if total_letters:
        score += 4.0 * (ascii_letters / total_letters)

    command_hits = sum(1 for tok in tokens if tok in COMMAND_WORDS)
    filler_hits = sum(1 for tok in tokens if tok in FILLER_WORDS)
    score -= command_hits * 2.2
    score -= filler_hits * 0.7

    if any(ch.isdigit() for ch in q):
        score += 0.4

    if any(tok in {"live", "remix", "cover", "acoustic"} for tok in tokens):
        score += 0.5

    if len(set(tokens)) == 1 and len(tokens) > 1:
        score -= 3.0

    return round(score, 3)


def looks_like_youtube_music_command(text: str) -> bool:
    low = _norm(text)
    if not low:
        return False

    if "youtube" in low or low.startswith("yt "):
        return True

    for prefix in ("play ", "puść ", "pusc ", "odtwórz ", "odtworz "):
        if low.startswith(prefix):
            return True

    return False


def split_youtube_command(text: str) -> tuple[str, str]:
    raw = " ".join((text or "").strip().split())
    low = raw.lower()

    for prefix in sorted(YOUTUBE_PREFIXES, key=len, reverse=True):
        if low == prefix:
            return raw.strip(), ""
        full = prefix + " "
        if low.startswith(full):
            return raw[:len(prefix)].strip(), raw[len(full):].strip()

    return raw.strip(), ""


def _extract_result_words(stt_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = stt_result.get("raw_result") or {}
    words = raw.get("result") or []
    return [item for item in words if isinstance(item, dict) and item.get("word")]


def _find_command_boundary_seconds(stt_result: dict[str, Any], prefix_text: str) -> float | None:
    words = _extract_result_words(stt_result)
    prefix_tokens = _tokenize(prefix_text)

    if not words or not prefix_tokens:
        return None

    word_tokens = [_norm_token(item.get("word", "")) for item in words]
    prefix_len = len(prefix_tokens)

    if word_tokens[:prefix_len] == prefix_tokens:
        return float(words[prefix_len - 1].get("end", 0.0)) + 0.08

    for idx, tok in enumerate(word_tokens[: min(len(word_tokens), 4)]):
        if tok in {"youtube", "yt"}:
            return float(words[idx].get("end", 0.0)) + 0.08

    return None


def _write_trimmed_wav(src_path: str, start_sec: float) -> str | None:
    if start_sec <= 0:
        return None

    with wave.open(src_path, "rb") as src:
        channels = src.getnchannels()
        sample_width = src.getsampwidth()
        rate = src.getframerate()
        frames = src.getnframes()
        start_frame = int(start_sec * rate)

        if start_frame <= 0 or start_frame >= frames:
            return None

        src.setpos(start_frame)
        audio = src.readframes(frames - start_frame)

    tmp = tempfile.NamedTemporaryFile(prefix="hal_voice_tail_", suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    with wave.open(tmp_path, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sample_width)
        dst.setframerate(rate)
        dst.writeframes(audio)

    return tmp_path


def _transcribe_tail_if_possible(
    wav_path: str,
    *,
    model_path: str,
    start_sec: float | None,
) -> dict[str, Any]:
    if not start_sec:
        return {"ok": False, "error": "missing_start_sec", "transcript": "", "tail_wav_path": None}

    tail_wav_path = _write_trimmed_wav(wav_path, start_sec)
    if not tail_wav_path:
        return {"ok": False, "error": "tail_wav_not_created", "transcript": "", "tail_wav_path": None}

    try:
        res = transcribe_wav(tail_wav_path, model_path=model_path)
        res["tail_wav_path"] = tail_wav_path
        return res
    finally:
        try:
            Path(tail_wav_path).unlink(missing_ok=True)
        except Exception:
            pass


def choose_best_music_query(
    pl_query: str,
    en_query_full: str,
    en_query_tail: str = "",
) -> tuple[str, str, dict[str, float]]:
    candidates = {
        "pl": _cleanup_music_query(pl_query),
        "en_full": _cleanup_music_query(_strip_known_en_prefix(en_query_full)),
        "en_tail": _cleanup_music_query(_strip_known_en_prefix(en_query_tail)),
    }

    scores = {name: _music_query_score(text) for name, text in candidates.items()}

    en_tail_text = candidates["en_tail"]
    if en_tail_text and not _looks_like_command_only(en_tail_text):
        tail_words = [w for w in en_tail_text.split() if w.strip()]
        if len(tail_words) >= 2:
            return en_tail_text, "en_tail", scores

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_name = ranked[0][0]
    best_text = candidates[best_name]

    if _looks_like_command_only(best_text):
        return "", "none", scores

    if not best_text:
        return candidates["pl"], "pl", scores

    if best_name.startswith("en") and scores[best_name] < scores["pl"] + 0.5 and candidates["pl"]:
        return candidates["pl"], "pl", scores

    return best_text, best_name, scores


def transcribe_wav_hybrid(
    wav_path: str,
    *,
    state: dict[str, Any] | None = None,
    model_path_pl: str | None = None,
) -> dict[str, Any]:
    state = state or {}

    pl_model = model_path_pl or state.get("stt_model_path") or "/home/hal/models/vosk/vosk-model-small-pl-0.22"
    pl_res = transcribe_wav(wav_path, model_path=pl_model)

    if not pl_res.get("ok"):
        return pl_res

    transcript_pl = (pl_res.get("transcript") or "").strip()
    result = dict(pl_res)
    result["transcript_pl"] = transcript_pl
    result["transcript_final"] = transcript_pl
    result["hybrid_used"] = False
    result["hybrid_reason"] = "disabled_or_not_needed"
    result["transcript_en"] = ""
    result["transcript_en_tail"] = ""
    result["query_pl"] = ""
    result["query_en"] = ""
    result["query_en_tail"] = ""
    result["query_final"] = ""
    result["query_source"] = "pl"
    result["query_scores"] = {}
    result["command_boundary_sec"] = None
    result["tail_error"] = ""

    hybrid_enabled = bool(state.get("hybrid_stt_enabled", False))
    hybrid_youtube_enabled = bool(state.get("hybrid_stt_youtube_enabled", False))
    model_path_en = str(Path(state.get("stt_model_path_en", "")).expanduser()) if state.get("stt_model_path_en") else ""

    if not hybrid_enabled:
        return result

    if not hybrid_youtube_enabled:
        result["hybrid_reason"] = "youtube_hybrid_disabled"
        return result

    if not looks_like_youtube_music_command(transcript_pl):
        result["hybrid_reason"] = "not_youtube_command"
        return result

    if not model_path_en:
        result["hybrid_reason"] = "missing_en_model_path"
        return result

    if not Path(model_path_en).exists():
        result["hybrid_reason"] = f"missing_en_model:{model_path_en}"
        return result

    prefix_pl, query_pl = split_youtube_command(transcript_pl)
    boundary_sec = _find_command_boundary_seconds(pl_res, prefix_pl)
    en_res = transcribe_wav(wav_path, model_path=model_path_en)
    en_tail_res = _transcribe_tail_if_possible(wav_path, model_path=model_path_en, start_sec=boundary_sec)

    transcript_en = (en_res.get("transcript") or "").strip()
    transcript_en_tail = (en_tail_res.get("transcript") or "").strip()

    query_en = _strip_known_en_prefix(transcript_en)
    query_en_tail = _cleanup_music_query(_strip_known_en_prefix(transcript_en_tail))
    query_final, query_source, query_scores = choose_best_music_query(query_pl, query_en, query_en_tail)

    result["hybrid_used"] = True
    result["hybrid_reason"] = "youtube_dual_pass_with_tail"
    result["transcript_en"] = transcript_en
    result["transcript_en_tail"] = transcript_en_tail
    result["query_pl"] = query_pl
    result["query_en"] = query_en
    result["query_en_tail"] = query_en_tail
    result["query_final"] = query_final
    result["query_source"] = query_source
    result["query_scores"] = query_scores
    result["command_boundary_sec"] = boundary_sec
    result["tail_error"] = en_tail_res.get("error", "")

    final_transcript = transcript_pl
    if prefix_pl and query_final:
        final_transcript = f"{prefix_pl} {query_final}".strip()
    elif query_final:
        final_transcript = query_final

    result["transcript"] = final_transcript
    result["text"] = final_transcript
    result["transcript_final"] = final_transcript
    result["transcript_source"] = query_source if query_final else "pl"

    if en_res.get("error") and not transcript_en:
        result["hybrid_reason"] = f"en_pass_failed:{en_res.get('error')}"
    elif en_tail_res.get("error") and not transcript_en_tail:
        result["hybrid_reason"] = f"youtube_dual_pass_tail_failed:{en_tail_res.get('error')}"

    return result


if __name__ == "__main__":
    raise SystemExit("voice_stt_hybrid.py is a module, not a standalone runner")
