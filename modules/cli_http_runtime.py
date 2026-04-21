from __future__ import annotations

import shlex


def handle_http_runtime(line: str, api) -> tuple[bool, str | None]:
    if line.startswith("geth "):
        parts = shlex.split(line)
        if len(parts) >= 2:
            url = parts[1]
            return True, api.http.get(url, want_headers=True)
        return True, "❌ Składnia: geth <URL>"

    if line.startswith("get "):
        parts = shlex.split(line)
        if len(parts) >= 2:
            url = parts[1]
            want_headers = ("--headers" in parts)
            return True, api.http.get(url, want_headers=want_headers)
        return True, "❌ Składnia: get <URL> [--headers]"

    return False, None
