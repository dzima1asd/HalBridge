from __future__ import annotations

from modules.query_router import route_query
from modules.agent_answer import answer_prompt


def handle_ai_line(line: str, api) -> tuple[bool, str | None]:
    if not line.startswith("ai "):
        return False, None

    prompt = line[3:].strip()
    route_decision = route_query(prompt)

    out_lines = [
        f"[DBG] ai prompt: {prompt!r}",
        f"[DBG] route: {route_decision}",
    ]

    try:
        result = answer_prompt(prompt, session_id=getattr(api, "session_id", "default"))
        out_lines.append(str(result))
    except Exception as e:
        out_lines.append(f"[AI][ERR] {type(e).__name__}: {e}")

    return True, "\n".join(out_lines)
