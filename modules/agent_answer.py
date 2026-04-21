from __future__ import annotations

from modules.agent_runtime import get_api
from modules.query_router import route_query
from modules.live_data_router import handle_live_data
from modules.knowledge_policy import is_factual_route, no_data_message
from modules.tools.registry import registry
from modules.runtime_objects import build_runtime_objects
from modules.cli_browser_yt_runtime import handle_browser_yt_runtime
from modules.voice_state import load_voice_state, save_voice_state


def _looks_like_hal_conversation(prompt: str) -> bool:
    low = (prompt or "").strip().lower()
    if not low:
        return False
    prefixes = (
        "hal ",
        "hal,",
        "hal:",
        "hej hal",
        "hello hal",
        "cześć hal",
        "czesc hal",
    )
    return low.startswith(prefixes) or low == "hal"


def _prepare_memory_search_query(prompt: str) -> str:
    low = (prompt or "").strip().lower()
    for prefix in ("hal ", "hal,", "hal:", "hej hal", "hello hal", "cześć hal", "czesc hal"):
        if low.startswith(prefix):
            low = low[len(prefix):].strip(" ,:;.-")
            break

    words = []
    stop = {
        "jak", "do", "mnie", "mi", "się", "sie", "i", "a", "oraz", "czy",
        "to", "ten", "ta", "te", "że", "ze", "na", "w", "z", "o", "od",
        "hal", "powinieneś", "powinienes", "powinien", "powinnas", "powinnaś",
    }
    for raw in low.replace("?", " ").replace("!", " ").replace(".", " ").replace(",", " ").split():
        w = raw.strip().lower()
        if len(w) < 3 or w in stop:
            continue
        words.append(w)
    return " ".join(words[:4])


def _build_hal_memory_context(api, session_id: str, prompt: str, *, max_items: int = 5, max_chars: int = 700) -> str:
    try:
        pinned = list(api.memory.pinned_memories(session_id))
    except Exception:
        pinned = []

    search_query = _prepare_memory_search_query(prompt)

    try:
        searched_rows = api.memory.search_memories(session_id, search_query or prompt, limit=3)
        searched = [str(r.get("content") or "").strip() for r in searched_rows if str(r.get("content") or "").strip()]
    except Exception:
        searched = []

    if not pinned and not searched:
        try:
            recent_rows = api.memory.list_memories(session_id, limit=3)
            searched = [str(r.get("content") or "").strip() for r in recent_rows if str(r.get("content") or "").strip()]
        except Exception:
            searched = []

    merged = []
    seen = set()

    for item in pinned + searched:
        clean = " ".join(str(item).split()).strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        merged.append(clean)
        if len(merged) >= max_items:
            break

    if not merged:
        return ""

    out = []
    total = 0
    for item in merged:
        row = f"- {item}"
        if out and total + len(row) + 1 > max_chars:
            break
        if not out and len(row) > max_chars:
            row = row[: max_chars - 3].rstrip() + "..."
        out.append(row)
        total += len(row) + 1

    if not out:
        return ""

    return (
        "To są zapisane preferencje i fakty o użytkowniku. Traktuj je jako ważny kontekst rozmowy z Halem. "
        "Jeśli pytanie dotyczy stylu odpowiedzi, preferencji użytkownika albo sposobu rozmowy, uwzględnij te informacje wprost w odpowiedzi. "
        "Nie cytuj pamięci dosłownie bez potrzeby, ale stosuj ją praktycznie.\n"
        + "\n".join(out)
    )


def _compose_hal_prompt(api, session_id: str, prompt: str) -> tuple[str, bool]:
    mem_block = _build_hal_memory_context(api, session_id, prompt)
    if not mem_block:
        return prompt, False
    enriched = (
        f"{mem_block}\n\n"
        f"Bieżący prompt użytkownika:\n{prompt}"
    )
    return enriched, True


def _render_web_result(out: dict, route: str | None) -> str:
    api = get_api(session_id="server_api")
    answer = None

    if isinstance(out, dict) and out.get("context"):
        try:
            answer = api.ask_ai_grounded(out["context"])
        except Exception:
            answer = None

    if isinstance(answer, str):
        cleaned = answer.strip()
        if cleaned.lower() in {
            "brak danych",
            "brak danych.",
            "brak pewnych danych z aktualnych źródeł.",
            "brak danych bieżących.",
        }:
            return no_data_message(route)
        if cleaned:
            return cleaned

    fallback = out.get("final_answer", out if isinstance(out, str) else None)
    if isinstance(fallback, str):
        cleaned = fallback.strip()

        if route == "current_facts":
            return no_data_message(route)

        if is_factual_route(route):
            if not cleaned or cleaned.lower() in {"brak danych", "brak danych.", "none"}:
                return no_data_message(route)
            return cleaned

        return cleaned or "Brak danych."

    if is_factual_route(route):
        return no_data_message(route)

    return "Brak danych."


def answer_prompt(prompt: str, session_id: str = "default") -> str:
    api = get_api(session_id=session_id)
    route_decision = route_query(prompt)

    if route_decision.route == "live_data":
        out = handle_live_data(prompt, route_decision)
        if isinstance(out, dict):
            return out.get("summary") or no_data_message(route_decision.route)
        return str(out) if out else no_data_message(route_decision.route)

    if route_decision.route == "browser_task":
        return "Ta klasa pytań została rozpoznana jako browser_task, ale nie jest jeszcze podpięta pod executor."

    if route_decision.route in {"current_facts", "news_research"}:
        try:
            from modules.tools.web_orchestrator import WebOrchestrator
            wo = WebOrchestrator(api, registry)
            out = wo.run(prompt, route=route_decision.route)
            return _render_web_result(out, route_decision.route)
        except Exception:
            return no_data_message(route_decision.route)

    low = (prompt or "").strip().lower()

    if low == "smart on":
        state = load_voice_state()
        state["intent_assist_mode"] = "on"
        save_voice_state(state)
        return "Smart on - włączono asystę rozumienia"

    if low == "smart off":
        state = load_voice_state()
        state["intent_assist_mode"] = "off"
        save_voice_state(state)
        return "Smart off - wyłączono asystę rozumienia"

    if low == "smart auto":
        state = load_voice_state()
        state["intent_assist_mode"] = "auto"
        save_voice_state(state)
        return "Smart auto - ustawiono asystę rozumienia na tryb automatyczny"

    if low == "smart status":
        state = load_voice_state()
        mode = str(state.get("intent_assist_mode", "off")).upper()
        provider = str(state.get("intent_assist_provider", "api")).upper()
        return f"Smart status - asysta rozumienia: {mode} | provider: {provider}"

    if low.startswith("smart provider "):
        provider = low[len("smart provider "):].strip()
        allowed = {"api", "local", "rules"}
        if provider not in allowed:
            return "❌ Dozwolone: smart provider api | local | rules"
        state = load_voice_state()
        state["intent_assist_provider"] = provider
        save_voice_state(state)
        return f"Smart provider - ustawiono provider: {provider.upper()}"

    if low == "smart limit status":
        state = load_voice_state()
        limit = int(state.get("intent_assist_api_limit", 100) or 0)
        calls = int(state.get("intent_assist_api_calls_total", 0) or 0)
        if limit > 0:
            left = max(limit - calls, 0)
            return f"Smart limit status - API calls: {calls}/{limit} | pozostało: {left}"
        return f"Smart limit status - API calls: {calls} | limit: OFF"

    if low == "smart limit reset":
        state = load_voice_state()
        state["intent_assist_api_calls_total"] = 0
        save_voice_state(state)
        limit = int(state.get("intent_assist_api_limit", 100) or 0)
        if limit > 0:
            return f"Smart limit reset - wyzerowano licznik API, limit: {limit}"
        return "Smart limit reset - wyzerowano licznik API"

    if low.startswith("yt "):
        try:
            _, browser = build_runtime_objects()
            handled, out = handle_browser_yt_runtime(prompt, browser)
            if handled:
                return out or "✅ Polecenie YouTube wykonane."
        except Exception as e:
            return f"❌ Błąd YouTube runtime: {type(e).__name__}: {e}"

    if _looks_like_hal_conversation(prompt):
        final_prompt, mem_used = _compose_hal_prompt(api, session_id, prompt)
        try:
            api.logger.log(
                "hal_mem_context",
                session_id=session_id,
                mem_used=mem_used,
                prompt_preview=(prompt or "")[:160],
                final_prompt_len=len(final_prompt or ""),
            )
        except Exception:
            pass
        return api.ask_ai_local(final_prompt)

    return api.ask_ai_local_stateless(prompt)
