#!/usr/bin/env python3
# camera_cleanup_report.py
# Uruchamiaj na SERWERZE. Czyści serwer + Pi, generuje raport i sprząta katalog HLS.

import os
import sys
import time
import subprocess
from datetime import datetime

SERVER_IP = "100.80.82.126"
PI_HOST = "zero@100.105.190.79"
TCP_PORT = 8554
HTTP_PORT = 8081

HLS_DIR = os.path.expanduser("~/cam_test")
M3U8 = os.path.join(HLS_DIR, "stream.m3u8")

REPORT_PATH = os.path.join(HLS_DIR, f"cleanup_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")


def sh(cmd: str) -> tuple[int, str]:
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    return r.returncode, out.strip()


def ssh(cmd: str) -> tuple[int, str]:
    full = f"ssh -o ConnectTimeout=4 -o BatchMode=yes {PI_HOST} {cmd!r}"
    return sh(full)


def section(lines, title):
    lines.append("")
    lines.append("=" * 78)
    lines.append(title)
    lines.append("=" * 78)


def main():
    os.makedirs(HLS_DIR, exist_ok=True)
    lines = []
    lines.append(f"HAL CAMERA CLEANUP REPORT @ {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"SERVER: {SERVER_IP}")
    lines.append(f"PI: {PI_HOST}")
    lines.append(f"DIR: {HLS_DIR}")
    lines.append(f"PORTS: tcp={TCP_PORT}, http={HTTP_PORT}")

    section(lines, "[0] SERVER: stan PRZED sprzątaniem (procesy + porty)")
    rc, out = sh("ps aux | egrep 'ffmpeg|http.server|python3 -m http.server|rpicam|libcamera|tcp://0.0.0.0:8554\\?listen=1' | grep -v grep || true")
    lines.append(out or "(brak)")
    rc, out = sh(f"ss -ltnp | egrep ':{TCP_PORT}|:{HTTP_PORT}' || true")
    lines.append(out or "(brak)")

    section(lines, "[1] PI: stan PRZED sprzątaniem (procesy + zajęte /dev/video*)")
    rc, out = ssh("bash -lc 'ps aux | egrep \"rpicam|libcamera\" | grep -v grep || true'")
    lines.append(out or "(brak)")
    rc, out = ssh("bash -lc 'lsof /dev/video* 2>/dev/null || true'")
    lines.append(out or "(brak)")

    section(lines, "[2] ACTION: zatrzymuję procesy na SERWERZE (ffmpeg/http)")
    actions = [
        f"pkill -TERM -f 'tcp://0.0.0.0:{TCP_PORT}\\?listen=1' || true",
        f"pkill -TERM -f 'ffmpeg .*{HLS_DIR}.*stream\\.m3u8' || true",
        f"pkill -TERM -f 'python3 -m http\\.server {HTTP_PORT}' || true",
        f"pkill -TERM -f 'http\\.server {HTTP_PORT}' || true",
        "sleep 0.5",
        f"pkill -KILL -f 'tcp://0.0.0.0:{TCP_PORT}\\?listen=1' || true",
        f"pkill -KILL -f 'ffmpeg .*{HLS_DIR}.*stream\\.m3u8' || true",
        f"pkill -KILL -f 'python3 -m http\\.server {HTTP_PORT}' || true",
        f"pkill -KILL -f 'http\\.server {HTTP_PORT}' || true",
    ]
    for cmd in actions:
        rc, out = sh(cmd)
        lines.append(f"$ {cmd}")
        if out:
            lines.append(out)

    section(lines, "[3] ACTION: zatrzymuję procesy kamery na PI (rpicam/libcamera)")
    rc, out = ssh("bash -lc 'pkill -TERM rpicam-vid 2>/dev/null || true; pkill -TERM rpicam-hello 2>/dev/null || true; pkill -TERM libcamera 2>/dev/null || true; sleep 0.5; pkill -KILL rpicam-vid 2>/dev/null || true; pkill -KILL rpicam-hello 2>/dev/null || true; pkill -KILL libcamera 2>/dev/null || true'")
    lines.append("SSH kill executed")
    if out:
        lines.append(out)

    section(lines, "[4] ACTION: czyszczenie katalogu HLS (serwer)")
    rc, out = sh(f"ls -lh {HLS_DIR} || true")
    lines.append("$ ls -lh (before)")
    lines.append(out or "(brak)")
    rc, out = sh(f"rm -f {HLS_DIR}/stream*.ts {HLS_DIR}/stream.m3u8 {HLS_DIR}/stream.m3u8.tmp || true")
    lines.append("$ rm -f stream*.ts stream.m3u8")
    if out:
        lines.append(out)
    rc, out = sh(f"ls -lh {HLS_DIR} || true")
    lines.append("$ ls -lh (after)")
    lines.append(out or "(brak)")

    section(lines, "[5] SERVER: stan PO sprzątaniu (procesy + porty)")
    rc, out = sh("ps aux | egrep 'ffmpeg|http.server|python3 -m http.server|rpicam|libcamera|tcp://0.0.0.0:8554\\?listen=1' | grep -v grep || true")
    lines.append(out or "(brak)")
    rc, out = sh(f"ss -ltnp | egrep ':{TCP_PORT}|:{HTTP_PORT}' || true")
    lines.append(out or "(brak)")

    section(lines, "[6] PI: stan PO sprzątaniu (/dev/video* + procesy)")
    rc, out = ssh("bash -lc 'ps aux | egrep \"rpicam|libcamera\" | grep -v grep || true'")
    lines.append(out or "(brak)")
    rc, out = ssh("bash -lc 'lsof /dev/video* 2>/dev/null || echo KAMERA_WOLNA'")
    lines.append(out or "(brak)")

    section(lines, "[7] WNIOSKI (prosto)")
    lines.append("- Jeśli port 8081/8554 był zajęty: zabite procesy powinny zniknąć w sekcji [5].")
    lines.append("- Jeśli kamera była zajęta: na Pi powinno być 'KAMERA_WOLNA' w sekcji [6].")
    lines.append("- Jeśli nadal coś siedzi: zobacz sekcje [5]/[6] i PIDy.")

    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n✔ Zapisano raport: {REPORT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nPrzerwano.")
        sys.exit(130)
