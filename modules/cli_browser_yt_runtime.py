from __future__ import annotations

def _strip_music_prefix(q: str) -> str:
    raw = (q or "").strip()
    low = raw.lower()

    prefixes = (
        "włącz piosenkę ",
        "wlacz piosenke ",
        "odtwórz ",
        "odtworz ",
        "puść ",
        "pusc ",
        "play ",
        "włącz ",
        "wlacz ",
    )

    for prefix in prefixes:
        if low.startswith(prefix):
            return raw[len(prefix):].strip()

    return raw


def handle_browser_yt_runtime(line: str, browser) -> tuple[bool, str | None]:
    if browser is None:
        return False, None

    raw = (line or "").strip()
    low = raw.lower().strip()

    # Proste sterowanie głośnością YouTube
    if raw and set(raw) == {"+"}:
        try:
            if browser.yt_is_muted():
                return True, browser.yt_unmute_restore()
            level = min(len(raw), 10) * 10
            return True, browser.yt_set_volume(level)
        except Exception:
            pass

    if low == "m":
        try:
            return True, browser.yt_mute()
        except Exception:
            pass

    if low == "u":
        try:
            return True, browser.yt_unmute_restore()
        except Exception:
            pass

    # Sterowanie odtwarzaniem
    if low in ("yt play", "yt pause", "yt pp", "yt stop", "stop"):
        return True, browser.yt_play_pause()
    if low in ("yt skip", "yt pomiń", "yt pomin", "yt pomin reklamę", "yt pomin reklame"):
        return True, browser.yt_skip_ad()
    if low in ("yt adguard on",):
        return True, browser.yt_adguard_on()
    if low in ("yt adguard off",):
        return True, browser.yt_adguard_off()
    if low in ("yt adguard", "yt adguard status"):
        return True, browser.yt_adguard_status()
    if low in ("yt next", "yt n"):
        return True, browser.yt_next()
    if low in ("yt prev", "yt p"):
        return True, browser.yt_prev()
    if low in ("yt vol+", "yt up"):
        return True, browser.yt_volume_up()
    if low in ("yt vol-", "yt down"):
        return True, browser.yt_volume_down()
    if low in ("yt fs", "yt fullscreen", "yt fullscrean"):
        return True, browser.yt_fullscreen()
    if low in ("yt help", "help yt", "yt pomoc", "yt pomocy"):
        return True, (
            "📺 YT HELP\n"
            "\n"
            "Szukanie i start:\n"
            "  yt metallica one\n"
            "  play ace of spades\n"
            "  puść rammstein du hast\n"
            "  odtwórz sabaton primo victoria\n"
            "\n"
            "Odtwarzanie:\n"
            "  yt play / yt pause / yt pp / stop\n"
            "  yt next / yt n\n"
            "  yt prev / yt p\n"
            "  yt skip / yt pomin / yt pomin reklamę\n"
            "\n"
            "Głośność:\n"
            "  yt vol+ / yt up\n"
            "  yt vol- / yt down\n"
            "  +          = 10%\n"
            "  ++         = 20%\n"
            "  +++        = 30%\n"
            "  ...\n"
            "  ++++++++++ = 100%\n"
            "  m = mute\n"
            "  u = unmute / restore\n"
            "\n"
            "Obraz:\n"
            "  yt fs / yt fullscreen\n"
            "\n"
            "AdGuard reklam:\n"
            "  yt adguard on\n"
            "  yt adguard off\n"
            "  yt adguard\n"
            "  yt adguard status\n"
            "\n"
            "Wyjście:\n"
            "  yt exit / yt quit / yt close\n"
            "\n"
            "Audio wyjście:\n"
            "  jbl on  = przełącz audio na JBL Charge 4\n"
            "  jbl off = wróć na głośnik standardowy\n"
            "\n"
            "Uwaga:\n"
            "  Start YouTube może automatycznie włączyć głośnik,\n"
            "  a yt close może go automatycznie wyłączyć, jeśli\n"
            "  został włączony automatycznie przez system."
        )

    # Zamykanie przeglądarki
    if low in ("yt exit", "yt quit", "yt close"):
        return True, browser.close(cleanup_speaker=True)

    # Wyszukiwanie YouTube
    if low.startswith("yt "):
        q = _strip_music_prefix(raw[3:].strip())
        if not q:
            return True, "❌ Podaj czego szukać na YouTube, np. yt ace of spades"
        return True, browser.yt_search_and_play(q)

    if low.startswith("youtube "):
        q = _strip_music_prefix(raw[8:].strip())
        if not q:
            return True, "❌ Podaj czego szukać na YouTube, np. youtube ace of spades"
        return True, browser.yt_search_and_play(q)

    if low.startswith("włącz youtube ") or low.startswith("wlacz youtube "):
        q = raw.split(" ", 2)[2].strip() if len(raw.split(" ", 2)) >= 3 else ""
        q = _strip_music_prefix(q)
        if not q:
            return True, "❌ Podaj czego szukać na YouTube, np. włącz youtube ace of spades"
        return True, browser.yt_search_and_play(q)

    # Skróty muzyczne bez prefiksu yt
    music_prefixes = (
        "play ",
        "włącz piosenkę ",
        "wlacz piosenke ",
        "puść ",
        "pusc ",
        "odtwórz ",
        "odtworz ",
    )

    if low.startswith(music_prefixes):
        q = _strip_music_prefix(raw)
        if not q:
            return True, "❌ Podaj tytuł utworu."
        return True, browser.yt_search_and_play(q)

    return False, None
