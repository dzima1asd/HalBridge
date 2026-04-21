from __future__ import annotations


def handle_about_runtime(line: str, cfg) -> tuple[bool, str | None]:
    if line != "about":
        return False, None

    version = (
        getattr(cfg, "APP_VERSION", None)
        or getattr(cfg, "VERSION", None)
        or "unknown"
    )

    return True, (
        f"🤖 Agent {version} | "
        f"Model: {cfg.OPENAI_MODEL} | "
        f"T={cfg.OPENAI_TEMPERATURE} | "
        f"MAXTOK={cfg.OPENAI_MAX_TOKENS}"
    )
