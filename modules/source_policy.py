from __future__ import annotations

from typing import Any
from modules.location_utils import normalize_location

KNOWN_LOCAL_SOURCES = {
    "poznan": ["poznan.pl", "epoznan.pl", "gloswielkopolski.pl", "radiopoznan.fm"],
    "poznań": ["poznan.pl", "epoznan.pl", "gloswielkopolski.pl", "radiopoznan.fm"],
    "białystok": ["radio.bialystok.pl", "poranny.pl", "wrotapodlasia.pl", "bialystokonline.pl"],
    "bialystok": ["radio.bialystok.pl", "poranny.pl", "wrotapodlasia.pl", "bialystokonline.pl"],
    "warszawa": ["tvnwarszawa.tvn24.pl", "warszawa.naszemiasto.pl", "um.warszawa.pl"],
    "kraków": ["krakow.pl", "lovekrakow.pl", "dziennikpolski24.pl"],
    "krakow": ["krakow.pl", "lovekrakow.pl", "dziennikpolski24.pl"],
    "wrocław": ["wroclaw.pl", "radiowroclaw.pl", "gazetawroclawska.pl"],
    "wroclaw": ["wroclaw.pl", "radiowroclaw.pl", "gazetawroclawska.pl"],
    "gdańsk": ["gdansk.pl", "trojmiasto.pl", "radiogdansk.pl"],
    "gdansk": ["gdansk.pl", "trojmiasto.pl", "radiogdansk.pl"],
}

POLAND_CURRENT_FACTS = [
    "gov.pl",
    "prezydent.pl",
    "sejm.gov.pl",
    "senat.gov.pl",
    "wikipedia.org",
]

US_CURRENT_FACTS = [
    "whitehouse.gov",
    "usa.gov",
    "congress.gov",
    "wikipedia.org",
]

POLAND_NEWS = [
    "pap.pl",
    "tvn24.pl",
    "rp.pl",
    "polsatnews.pl",
    "onet.pl",
    "interia.pl",
    "wp.pl",
]

WORLD_NEWS = [
    "reuters.com",
    "bbc.com",
    "theguardian.com",
    "apnews.com",
]

FICTION_SOURCES = [
    "fandom.com",
    "wikia.com",
    "wikipedia.org",
]

def _norm(text: str) -> str:
    return (text or "").strip().lower()

def extract_location_hint(query: str) -> str | None:
    q = _norm(query)

    aliases = {
        "białystok": ["białystok", "białymstoku", "bialystok", "bialymstoku"],
        "warszawa": ["warszawa", "warszawie"],
        "kraków": ["kraków", "krakowie", "krakow", "krakowie"],
        "wrocław": ["wrocław", "wrocławiu", "wroclaw", "wroclawiu"],
        "gdańsk": ["gdańsk", "gdańsku", "gdansk", "gdansku"],
        "poznań": ["poznań", "poznaniu", "poznan", "poznaniu"],
        "lublin": ["lublin", "lublinie"],
        "olsztyn": ["olsztyn", "olsztynie"],
        "szczecin": ["szczecin", "szczecinie"],
    }

    for canonical, forms in aliases.items():
        if any(f in q for f in forms):
            return canonical

    for key in KNOWN_LOCAL_SOURCES.keys():
        if key in q:
            return key

    return None

def detect_scope(query: str, route: str | None, domain: str | None) -> str:
    q = _norm(query)
    loc = extract_location_hint(q)

    if route == "current_facts":
        if any(x in q for x in ["trump", "usa", "ameryk", "white house", "vice president", "wiceprezydent", "vance"]):
            return "international"
        if any(x in q for x in ["polski", "polska", "sejm", "senat", "premier", "prezydent", "minister", "rząd", "rzad"]):
            return "country"
        if loc:
            return "local"
        return "generic"

    if route == "news_research":
        if loc:
            return "local"
        if any(x in q for x in ["w polsce", "polska", "krajowej", "krajowe", "w kraju"]):
            return "country"
        return "international"

    return "generic"

def get_source_policy(query: str, route: str | None, domain: str | None) -> dict[str, Any]:
    q = _norm(query)
    loc = extract_location_hint(q)
    scope = detect_scope(q, route, domain)

    preferred_domains: list[str] = []
    policy_name = "generic_search_policy"

    if domain == "fiction_popculture":
        policy_name = "fiction_popculture"
        preferred_domains = FICTION_SOURCES[:]

    elif route == "current_facts":
        if scope == "country":
            policy_name = "current_facts_pl"
            preferred_domains = POLAND_CURRENT_FACTS[:]
        elif scope == "international":
            policy_name = "current_facts_us_or_global"
            preferred_domains = US_CURRENT_FACTS[:]
        elif scope == "local" and loc and loc in KNOWN_LOCAL_SOURCES:
            policy_name = "current_facts_local"
            preferred_domains = KNOWN_LOCAL_SOURCES.get(loc, [])[:]
        else:
            policy_name = "current_facts_generic"
            preferred_domains = POLAND_CURRENT_FACTS[:] + US_CURRENT_FACTS[:2]

    elif route == "news_research":
        if scope == "local" and loc:
            policy_name = "local_news_generic"
            preferred_domains = KNOWN_LOCAL_SOURCES.get(loc, [])[:]
        elif scope == "country":
            policy_name = "country_news_pl"
            preferred_domains = POLAND_NEWS[:]
        elif scope == "international":
            policy_name = "world_news"
            preferred_domains = WORLD_NEWS[:]

    return {
        "policy_name": policy_name,
        "scope": scope,
        "location": loc,
        "preferred_domains": preferred_domains,
        "fallback_to_search": True,
        "max_direct_sources": 5,
    }
