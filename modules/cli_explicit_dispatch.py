from __future__ import annotations
# explicit CLI operator dispatch for ai / intent / explicit codegen

from modules.cli_ai import handle_ai_line
from modules.cli_intent import handle_intent_line
from modules.cli_codegen import handle_codegen_line


def handle_explicit_dispatch(line: str, api):
    handled, out = handle_ai_line(line, api)
    if handled:
        return True, out, False

    handled, out = handle_intent_line(line)
    if handled:
        return True, out, False

    handled, out = handle_codegen_line(line, api)
    if handled:
        return True, out, True

    return False, None, False
