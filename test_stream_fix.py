import subprocess
import time
import os

# Test pattern zamiast kamery
test_cmd = (
    "ffmpeg -hide_banner -loglevel error "
    "-f lavfi -i testsrc=size=640x480:rate=15 "
    "-c:v libx264 -preset ultrafast -tune zerolatency "
    "-f h264 - 2>/dev/null"
)

print("Testing with test pattern...")
proc = subprocess.Popen(test_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(2)
print(f"Process alive: {proc.poll() is None}")
proc.terminate()
