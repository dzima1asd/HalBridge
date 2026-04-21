from __future__ import annotations

import re
from modules.route_types import RouteDecision
from modules.location_utils import normalize_location

LOCAL_PATTERNS = [
    r"^co to jest\b",
    r"^czym jest\b",
    r"^jak dzia[ał]a\b",
    r"^wyja[sś]nij\b",
    r"^zdefiniuj\b",
    r"^opisz\b",
    r"^definicja\b",
]

LIVE_DATA_PATTERNS = [
    r"\bpogoda\b",
    r"\btemperatura\b",
    r"\bkurs\b",
    r"\bwalut\w*\b",
    r"\bdolar\b",
    r"\beuro\b",
    r"\bbtc\b",
    r"\bbitcoin\b",
    r"\bcena\b.*\b(dolara|euro|btc|bitcoina)\b",
    r"\bile wynosi\b.*\bkurs\b",
]

NEWS_PATTERNS = [
    r"\bco nowego\b",
    r"\baktualno[sś]ci\b",
    r"\bnewsy\b",
    r"\bwiadomo[sś]ci\b",
    r"\bwydarzy[łl]o si[eę]\b",
    r"\bnajnowsze\b",
    r"\bdzi[sś]\b.*\bna [sś]wiecie\b",
    r"\bdzi[sś]\b.*\bw\b",
]

CURRENT_FACTS_PATTERNS = [
    r"^kto jest\b",
    r"^kto obecnie\b",
    r"^kto aktualnie\b",
    r"^kto pełni\b",
    r"^kto pelni\b",
    r"^jaki jest obecny\b",
    r"^jaki jest aktualny\b",
    r"^kto jest .*?(prezydentem|premierem|ministrem|marszałkiem|marszalkiem|wojewodą|wojewoda|prezesem|szefem|zastępcą|zastepca|wiceprezydentem|vice president|vice-president)\b",
]

CURRENT_FACTS_ROLE_HINTS = [
    "prezydent",
    "premier",
    "minister",
    "marszałek",
    "marszalek",
    "wojewoda",
    "prezes",
    "szef",
    "zastępca",
    "zastepca",
    "wiceprezydent",
    "vice president",
    "vice-president",
    "rząd",
    "rząd",
    "rządzie",
    "rzadzie",
    "gabinet",
    "administracja",
    "senator",
    "poseł",
    "posel",
    "burmistrz",
    "prezydent miasta",
]


EVENT_NEWS_PATTERNS = [
    r"\bzosta[łl] wybran\w*\b",
    r"\bwybran\w*\b.*\b(dzi[sś]|dzis|dzisiaj)\b",
    r"\bwybory\b",
    r"\bwygra[łl]\b.*\bwybory\b",
    r"\bzosta[łl] mianowan\w*\b",
    r"\bzosta[łl] powo[łl]an\w*\b",
    r"\bpowo[łl]ano\b",
    r"\bmianowano\b",
]

BROWSER_PATTERNS = [
    r"^otw[oó]rz\b",
    r"^wejd[zź]\b",
    r"^kliknij\b",
    r"^zaloguj\b",
    r"^przejd[zź]\b",
    r"^poka[zż]\b.*\bna stronie\b",
    r"^wyszukaj\b.*\bna stronie\b",
    r"^poka[zż]\b.*\bofert\w*\b",
    r"^znajd[zź]\b.*\bsklep\b",
    r"^wyszukaj\b.*\ballegro\b",
    r"^poka[zż]\b.*\ballegro\b",
    r"^gdzie kupi[cć]\b",
    r"^kup\b",
]

LOCATION_HINTS = [
    "w białymstoku", "w bialymstoku", "białystok", "bialystok",
    "w warszawie", "warszawa", "w polsce", "polska",
]

TIME_HINTS = [
    "dziś", "dzis", "dzisiaj", "jutro", "teraz", "aktualnie", "obecnie", "ostatnio",
]

def _has_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def _extract_location(text: str) -> str | None:
    t = text.lower()
    loc = normalize_location(t)
    if loc:
        return loc
    for item in LOCATION_HINTS:
        if item in t:
            return item
    return None

def _extract_timeframe(text: str) -> str | None:
    t = text.lower()
    for item in TIME_HINTS:
        if item in t:
            return item
    return None

def route_query(text: str, context: dict | None = None) -> RouteDecision:
    context = context or {}
    raw = (text or "").strip()
    t = raw.lower()

    if _has_any_pattern(t, BROWSER_PATTERNS):
        return RouteDecision(
            route="browser_task",
            reason="matched browser interaction pattern / shopping intent",
            confidence=0.95,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if _has_any_pattern(t, LIVE_DATA_PATTERNS):
        topic = None
        if "pogoda" in t or "temperatura" in t:
            topic = "weather"
        elif any(x in t for x in ["kurs", "dolar", "euro", "walut"]):
            topic = "fx"
        elif any(x in t for x in ["btc", "bitcoin"]):
            topic = "crypto"
        elif any(x in t for x in ["imieniny", "kto obchodzi", "kto ma dziś imieniny", "kto ma dzis imieniny"]):
            topic = "calendar"
        return RouteDecision(
            route="live_data",
            reason="matched structured live-data pattern",
            confidence=0.92,
            topic=topic,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if _has_any_pattern(t, EVENT_NEWS_PATTERNS):
        return RouteDecision(
            route="news_research",
            reason="matched event/change-of-state political/news pattern",
            confidence=0.93,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if _has_any_pattern(t, CURRENT_FACTS_PATTERNS) or (
        t.startswith("kto ") and any(h in t for h in CURRENT_FACTS_ROLE_HINTS)
    ):
        return RouteDecision(
            route="current_facts",
            reason="matched current role/person/political fact pattern",
            confidence=0.91,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if _has_any_pattern(t, NEWS_PATTERNS):
        return RouteDecision(
            route="news_research",
            reason="matched recency/news pattern",
            confidence=0.90,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if _has_any_pattern(t, LOCAL_PATTERNS):
        return RouteDecision(
            route="local_knowledge",
            reason="matched local knowledge pattern",
            confidence=0.88,
        )

    if any(x in t for x in ["co nowego", "aktualne", "najnowsze", "wydarzenia", "wiadomości", "wiadomosci"]):
        return RouteDecision(
            route="news_research",
            reason="fallback recency/news keywords",
            confidence=0.75,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if (
        ("dziś" in t or "dzis" in t or "dzisiaj" in t or "obecnie" in t or "aktualnie" in t)
        and any(x in t for x in ["imieniny", "kto jest", "kto obchodzi", "stanowisko", "funkcj"])
    ):
        route = "live_data" if any(x in t for x in ["imieniny", "kto obchodzi"]) else "current_facts"
        reason = "fallback temporal factual query"
        return RouteDecision(
            route=route,
            reason=reason,
            confidence=0.72,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    if any(x in t for x in ["najbardziej sensowny", "warto się uczyć", "warto sie uczyc", "opłaca się", "oplaca sie", "najlepszy język", "najlepszy jezyk"]):
        return RouteDecision(
            route="local_knowledge",
            reason="current recommendation question handled as local knowledge for now",
            confidence=0.68,
            location=_extract_location(t),
            timeframe=_extract_timeframe(t),
        )

    return RouteDecision(
        route="local_knowledge",
        reason="default fallback to local knowledge",
        confidence=0.60,
        location=_extract_location(t),
        timeframe=_extract_timeframe(t),
    )
