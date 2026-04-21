from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any
import re


@dataclass
class NewsResult:
    title: str
    snippet: str
    url: str
    source: str = ""


@dataclass
class ResearchResponse:
    ok: bool
    answer: str
    sources: List[NewsResult] = field(default_factory=list)
    error: Optional[str] = None


def extract_urls(text: str) -> List[str]:
    return re.findall(r"https?://\S+", text or "")


def validate_news_results(results: List["NewsResult"], min_sources: int = 1) -> bool:
    valid: List[NewsResult] = []
    for r in results:
        if not r:
            continue
        if not r.title or not r.url:
            continue
        if not r.url.startswith(("http://", "https://")):
            continue
        valid.append(r)
    return len(valid) >= min_sources


def format_news_response(results: List["NewsResult"], city: str, timeframe: str) -> ResearchResponse:
    if not validate_news_results(results, min_sources=1):
        return ResearchResponse(
            ok=False,
            answer=f"Nie znalazłem potwierdzonych aktualnych informacji dla: {city} ({timeframe}).",
            sources=[],
            error="insufficient_sources",
        )

    lines = [f"Oto, co nowego {timeframe} w {city}:"]
    for i, r in enumerate(results[:5], 1):
        lines.append(f"{i}. {r.title}")
        if r.snippet:
            lines.append(f"   {r.snippet}")
        lines.append(f"   Źródło: {r.url}")

    return ResearchResponse(
        ok=True,
        answer="\n".join(lines),
        sources=results[:5],
        error=None,
    )


def guard_final_answer(route: str, answer_text: str, sources: List["NewsResult"]) -> str:
    if route == "news_research":
        has_url_in_text = bool(extract_urls(answer_text))
        has_sources = bool(sources)
        if not has_url_in_text and not has_sources:
            return "Nie mogę podać aktualnych newsów bez potwierdzonych źródeł."
    return answer_text


def handle_news_research(city: str, timeframe: str, web_search_fn: Callable[..., Any]) -> ResearchResponse:
    results = web_search_fn(query=f"co nowego {timeframe} w {city}")

    if not isinstance(results, list):
        return ResearchResponse(
            ok=False,
            answer="Moduł research nie zwrócił poprawnych danych.",
            sources=[],
            error="bad_research_payload",
        )

    parsed: List[NewsResult] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        parsed.append(
            NewsResult(
                title=str(item.get("title", "")).strip(),
                snippet=str(item.get("snippet", "")).strip(),
                url=str(item.get("url", "")).strip(),
                source=str(item.get("source", "")).strip(),
            )
        )

    return format_news_response(parsed, city=city, timeframe=timeframe)
