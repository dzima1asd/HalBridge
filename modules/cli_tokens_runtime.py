from __future__ import annotations


def handle_tokens_runtime(line: str, api) -> tuple[bool, str | None]:
    if line == "tokens":
        return True, api.meter.summary()

    if line == "tokens report":
        return True, api.meter.report()

    if line == "tokens reset":
        api.meter.reset()
        return True, "✅ Liczniki tokenów wyzerowane."

    return False, None
