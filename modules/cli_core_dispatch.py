from __future__ import annotations
# natural CLI dispatch for non-explicit input: codegen and kernel-backed intent flow

def handle_core_dispatch(line: str, api):
    basic_cli_commands = {"exit", "quit", "q", "help", "?", "stop"}
    meta_prefixes = (
        "modules ",
        "module ",
        "model ",
        "temp ",
        "max ",
        "max_tokens ",
        "strict ",
        "net ",
        "diag",
    )

    line_l = (line or "").lower().strip()
    yt_commands = {
        "yt play", "yt pause", "yt pp",
        "yt next", "yt n",
        "yt prev", "yt p",
        "yt vol+", "yt up",
        "yt vol-", "yt down",
        "yt fs", "yt fullscreen",
    }

    browser_prefixes = (
        "web ",
        "otwórz", "otworz",
        "pokaż", "pokaz",
        "znajdź", "znajdz",
        "wyszukaj",
    )

    music_prefixes = (
        "play ",
        "włącz piosenkę ", "wlacz piosenke ",
        "puść ", "pusc ",
        "odtwórz ", "odtworz ",
    )

    should_skip_natural_dispatch = (
        line_l in basic_cli_commands
        or line_l in yt_commands
        or line_l.startswith("yt ")
        or any(line_l.startswith(prefix) for prefix in music_prefixes)
        or line_l.startswith("!")
        or line_l.startswith("intent ")
        or line_l.startswith("ai ")
        or any(line_l.startswith(prefix) for prefix in browser_prefixes)
        or any(line_l.startswith(prefix) for prefix in meta_prefixes)
    )

    if should_skip_natural_dispatch:
        return False, None, False

    if line_l.startswith("code "):
        from modules.cli_codegen import handle_codegen_line
        handled, output = handle_codegen_line(line, api)
        if handled:
            return True, output, True
        return False, None, False

    from modules.cli_kernel_bridge import execute_cli_intent
    result = execute_cli_intent(line)

    if not isinstance(result, dict):
        return False, None, False

    reply = (result.get("reply_text") or "").strip()
    output = reply if reply else result
    route = result.get("route")
    action = result.get("action")
    error = result.get("error")

    if route == "intent" and action == "plan_execute":
        return True, output, False

    if route == "intent" and action == "ask":
        data = result.get("data") or {}
        missing = data.get("missing_slots") or []
        intent_name = data.get("intent")
        if intent_name == "iot.toggle" and "device" in missing:
            return False, None, False
        return True, output, True

    if route == "intent" and error:
        if error == "unknown_intent":
            return False, None, False
        return True, output, False

    return False, None, False
