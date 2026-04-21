#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cam_pi.py
=========
Moduł sterowania kamerą Raspberry Pi (u Ciebie: Zero 2 W) przez SSH.

Co potrafi:
- połączyć się z Pi po SSH (sshpass)
- sprawdzić dostępne kamery (rpicam-still --list-cameras)
- zrobić jedno zdjęcie (rpicam-still)
- zrobić serię zdjęć (pętla: 2 zdjęcia/s domyślnie)
- nagrać film przez N sekund (rpicam-vid)
- skopiować wynik na SERWER (HALbridge) do /home/hal/HALbridge/media/camera/

Dodatkowo:
- handle_camera_command(): przyjmuje tekst typu:
    "zrób zdjęcie" / "zrob zdjecie" / "zrub zdjiecie"
    "rób zdjęcia" / "rób 20 zdjęć" / "zrób 2 zdjęcia"
    "nagraj film" / "nagraj film 60" / "nagraj film 3:30"
  i wywołuje odpowiednie funkcje.

Konfiguracja (env z priorytetem):
  CAM_PI_HOST, CAM_PI_PASS, CAM_PI_PORT, CAM_PI_HOME, CAM_PI_OUTDIR
"""

import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from typing import Optional

# =========================================================
# KONFIGURACJA (ENV -> default)
# =========================================================
PI_HOST = os.getenv("CAM_PI_HOST", "zero@PI_HOST_IP")
PI_PASS = os.getenv("CAM_PI_PASS", "niemodlin")
PI_PORT = os.getenv("CAM_PI_PORT", "22")
PI_HOME = os.getenv("CAM_PI_HOME", "/home/zero")

# gdzie na SERWERZE mają lądować pliki
OUTDIR = os.getenv("CAM_PI_OUTDIR", "/home/hal/HALbridge/media/camera")


# =========================================================
# NARZĘDZIA SYSTEMOWE
# =========================================================
def run(cmd, timeout=120):
    """Uruchamia komendę lokalnie i zwraca CompletedProcess."""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def ssh(cmd: str) -> str:
    """Wykonuje polecenie na Raspberry Pi przez SSH (hasło przez sshpass)."""
    ssh_cmd = [
        "sshpass", "-p", PI_PASS,
        "ssh",
        "-p", str(PI_PORT),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        PI_HOST,
        "--",
        cmd,
    ]
    p = run(ssh_cmd)
    if p.returncode != 0:
        return f"❌ SSH error:\n{p.stderr.strip()}"
    return (p.stdout or "").strip()


def scp_from_to_path(remote_file: str, local_path: str) -> str:
    """
    Kopiuje plik z Raspberry Pi do konkretnej ścieżki na SERWERZE (pełna ścieżka pliku).
    Przykład: local_path="/home/hal/HALbridge/media/camera/foto.jpg"
    """
    pdir = os.path.dirname(local_path)
    os.makedirs(pdir, exist_ok=True)

    scp_cmd = [
        "sshpass", "-p", PI_PASS,
        "scp",
        "-P", str(PI_PORT),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"{PI_HOST}:{remote_file}",
        local_path,
    ]
    p = run(scp_cmd, timeout=180)
    if p.returncode != 0:
        return f"❌ SCP error:\n{p.stderr.strip()}"
    return f"✅ Zapisano na serwerze: {local_path}"


# =========================================================
# KOMENDY KAMERY (WYKONANIE)
# =========================================================
def list_cameras() -> str:
    """Wyświetla wykryte kamery."""
    return ssh("rpicam-still --list-cameras")


def take_photo(name: str = "foto.jpg") -> str:
    """
    Robi jedno zdjęcie na Raspberry Pi i kopiuje je na SERWER HALbridge.
    Zapis: OUTDIR/name
    """
    remote_path = f"{PI_HOME}/{name}"
    local_path = os.path.join(OUTDIR, name)

    # 1) zdjęcie na Pi
    cmd = f"rpicam-still -o {shlex.quote(remote_path)}"
    res = ssh(cmd)

    # 2) info o pliku na Pi (czasem się przydaje)
    info = ssh(f"ls -lh {shlex.quote(remote_path)}")

    # 3) pobranie na serwer
    pulled = scp_from_to_path(remote_path, local_path)

    return f"{res}\n{info}\n{pulled}".strip()


def take_photo_series(count: int = 5, fps: float = 2.0) -> str:
    """
    Robi serię zdjęć.
    Domyślnie: 5 zdjęć, 2 zdjęcia / sek.
    """
    if count < 1:
        count = 1
    if fps <= 0:
        fps = 2.0

    delay = 1.0 / fps
    results = []

    for i in range(count):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        name = f"series_{ts}_{i+1}.jpg"
        results.append(take_photo(name))
        if i < count - 1:
            time.sleep(delay)

    return "\n".join(results)


def record_video_seconds(seconds: int = 30) -> str:
    """
    Nagrywa film przez podaną liczbę sekund.
    Zapis: OUTDIR/video_YYYYmmdd_HHMMSS.h264
    """
    if seconds < 1:
        seconds = 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"video_{ts}.h264"
    ms = int(seconds * 1000)

    remote_path = f"{PI_HOME}/{name}"
    local_path = os.path.join(OUTDIR, name)

    cmd = f"rpicam-vid -o {shlex.quote(remote_path)} -t {ms}"
    res = ssh(cmd)

    info = ssh(f"ls -lh {shlex.quote(remote_path)}")
    pulled = scp_from_to_path(remote_path, local_path)

    return f"{res}\n{info}\n{pulled}".strip()


# =========================================================
# PARSER "LUDZKICH" KOMEND (WEJŚCIE)
# =========================================================
def parse_time_to_seconds(value: str) -> int:
    """
    Zamienia zapis czasu na sekundy.
    Obsługuje:
      - "60"   -> 60
      - "3:30" -> 210
    """
    value = (value or "").strip()
    if not value:
        return 0
    if ":" in value:
        m, s = value.split(":", 1)
        return int(m) * 60 + int(s)
    return int(value)


def _cam_norm(s: str) -> str:
    """
    Normalizacja pod komendy kamery:
    - działa 'zrób zdjęcie' i 'zrob zdjecie'
    - toleruje literówki typu: 'zrub zdjiecie'
    """
    if not s:
        return ""
    t = s.strip().lower()

    # ogonki -> ascii (jak w hardware_bridge)
    t = (
        t.replace("ą", "a").replace("ć", "c").replace("ę", "e")
         .replace("ł", "l").replace("ń", "n").replace("ó", "o")
         .replace("ś", "s").replace("ż", "z").replace("ź", "z")
    )

    # typowe literówki / fonetyka
    fixes = {
        "zrub": "zrob",
        "zdjiecie": "zdjecie",
        "zdjiecia": "zdjecia",
        "zdjcia": "zdjecia",
        "zdjece": "zdjecie",
        "zdjec": "zdjec",  # rdzeń
    }
    for bad, good in fixes.items():
        t = t.replace(bad, good)

    # spacje
    t = re.sub(r"\s+", " ", t).strip()
    return t


def handle_camera_command(text: str) -> Optional[str]:
    """
    Przyjmuje tekst wpisany w agencie i jeśli to komenda kamery, wykonuje ją
    i zwraca output (string). Jeśli nie rozpoznano -> None.

    Obsługuje:
      - "zrob zdjecie" / "zrob 2 zdjecia" / "rob zdjecia" / "rob 20 zdjec"
      - "nagraj film" / "nagraj film 60" / "nagraj film 3:30"
    """
    t = _cam_norm(text)

    # --- FILM ---
    if t.startswith("nagraj film"):
        seconds = 30  # domyślnie

        m = re.search(r"nagraj film\s+(\d+:\d+)", t)
        if m:
            seconds = parse_time_to_seconds(m.group(1))
        else:
            m2 = re.search(r"nagraj film\s+(\d+)", t)
            if m2:
                seconds = int(m2.group(1))

        if seconds < 1:
            seconds = 30

        return record_video_seconds(seconds=seconds)

    # --- ZDJĘCIA ---
    # domyślnie:
    # - "zrob zdjecie" -> 1
    # - "rob zdjecia"  -> 5
    if ("zdjec" in t) and (t.startswith("zrob") or t.startswith("rob")):
        count = 1
        if t.startswith("rob"):
            count = 5

        m = re.search(r"\b(\d+)\b", t)
        if m:
            count = int(m.group(1))

        if count <= 1:
            return take_photo()
        return take_photo_series(count=count, fps=2.0)

    return None


# =========================================================
# TRYB CLI (opcjonalny)
# =========================================================
def _usage() -> str:
    return (
        "Użycie:\n"
        "  python3 cam_pi.py list\n"
        "  python3 cam_pi.py photo [nazwa.jpg]\n"
        "  python3 cam_pi.py burst [count] [fps]\n"
        "  python3 cam_pi.py video [seconds]\n"
        "  python3 cam_pi.py cmd \"zrob zdjecie\" | \"rob 20 zdjec\" | \"nagraj film 3:30\"\n"
    )


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print("📷 Dostępne kamery:")
        print(list_cameras())
        print("\n📸 Test zdjęcia:")
        print(take_photo("foto.jpg"))
        raise SystemExit(0)

    mode = args[0].lower()

    if mode == "list":
        print(list_cameras())
        raise SystemExit(0)

    if mode == "photo":
        name = args[1] if len(args) > 1 else "foto.jpg"
        print(take_photo(name))
        raise SystemExit(0)

    if mode == "burst":
        count = int(args[1]) if len(args) > 1 else 5
        fps = float(args[2]) if len(args) > 2 else 2.0
        print(take_photo_series(count=count, fps=fps))
        raise SystemExit(0)

    if mode == "video":
        seconds = int(args[1]) if len(args) > 1 else 30
        print(record_video_seconds(seconds=seconds))
        raise SystemExit(0)

    if mode == "cmd":
        raw = " ".join(args[1:]).strip()
        out = handle_camera_command(raw)
        if out is None:
            print("❌ Nie rozpoznano komendy kamery.")
            print(_usage())
        else:
            print(out)
        raise SystemExit(0)

    print("❌ Nieznany tryb.\n")
    print(_usage())
    raise SystemExit(2)
