#!/usr/bin/env bash
set -u

PI_HOST="zero@192.168.100.16"
SERVER_IP="192.168.100.12"
TCP_PORT=8554
HTTP_PORT=8081
STREAM_DIR="/home/hal/HALbridge/media/stream"

echo "=== STREAM DIAGNOSTYKA START ==="

echo
echo "[1] Sprawdzam procesy ffmpeg / rpicam / http.server"
ps aux | egrep 'ffmpeg|rpicam|http.server' | grep -v grep || echo "  (brak)"

echo
echo "[2] Sprawdzam porty lokalne"
ss -ltnp | egrep "(:$TCP_PORT|:$HTTP_PORT)" || echo "  (porty zamknięte)"

echo
echo "[3] Test połączenia TCP (czy Pi może wysłać dane)"
timeout 3 bash -c "</dev/tcp/127.0.0.1/$TCP_PORT" && echo "  TCP OK" || echo "  TCP FAIL"

echo
echo "[4] Test HTTP HLS"
curl -s --max-time 3 http://127.0.0.1:$HTTP_PORT/stream.m3u8 | head -n 5 || echo "  HLS FAIL"

echo
echo "[5] Zawartość katalogu stream"
ls -lh "$STREAM_DIR" || echo "  brak katalogu"

echo
echo "[6] Test SSH + kamery (surowy rpicam-vid)"
ssh "$PI_HOST" "ps aux | grep rpicam | grep -v grep" || echo "  brak rpicam"

echo
echo "[7] Próba ręcznego startu kamery (3s)"
ssh "$PI_HOST" "timeout 3 rpicam-vid --nopreview -t 3000 --width 640 --height 480 -o /tmp/test.h264 && echo OK || echo FAIL"

echo
echo "[8] Test przesyłu TCP z Pi → serwer"
ssh "$PI_HOST" "timeout 3 rpicam-vid --nopreview -t 3000 -o tcp://$SERVER_IP:$TCP_PORT && echo TCP_OK || echo TCP_FAIL"

echo
echo "=== STREAM DIAGNOSTYKA KONIEC ==="
