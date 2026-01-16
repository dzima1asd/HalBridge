#!/usr/bin/env python3
"""
HAL Stream Engine - FINAL VERSION
Based on 100% working stream_live_deepseek_2.py
"""

import subprocess
import os
import time
import sys
import signal
import json
import threading
import http.server
import socketserver
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, Dict, Any, List
from collections import deque

import paho.mqtt.client as mqtt

# ================= CONFIGURATION =================

# MQTT Configuration
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
BASE_TOPIC = "hal/stream"
T_CMD = f"{BASE_TOPIC}/cmd"
T_STATUS = f"{BASE_TOPIC}/status"
T_HEALTH = f"{BASE_TOPIC}/health"
T_EVENT = f"{BASE_TOPIC}/event"

# System Configuration
PI_HOST = "zero@192.168.100.16"  # SSH to Raspberry Pi
HTTP_PORT = 8081  # Port for HTTP server

# Directories
BASE_DIR = Path.home() / "HALbridge" / "media"
BASE_DIR.mkdir(parents=True, exist_ok=True)

STREAM_DIR = BASE_DIR / "stream"
SNAPSHOT_DIR = BASE_DIR / "snapshots" 
RECORD_DIR = BASE_DIR / "recordings"
LOG_DIR = BASE_DIR / "logs"

for d in [STREAM_DIR, SNAPSHOT_DIR, RECORD_DIR, LOG_DIR]:
    d.mkdir(exist_ok=True)

# Commands (100% WORKING from stream_live_deepseek_2.py)
PI_CAM_CMD = (
    "rpicam-vid -t 0 "
    "--codec h264 "
    "--profile baseline "
    "--intra 30 "
    "--inline "
    "--width 640 --height 480 --framerate 30 "
    "--exposure normal "
    "--awb auto "
    "--gain 2.0 "
    "--brightness 0.3 "
    "-o -"
)

FFMPEG_HLS_CMD = [
    "ffmpeg",
    "-loglevel", "error",           # Only errors
    "-fflags", "+genpts",
    "-f", "h264",
    "-i", "pipe:0",                # Data from Pi
    "-c:v", "copy",                # NO recompression - minimal latency!
    "-f", "hls",
    "-hls_time", "2",              # Segment length 2 seconds
    "-hls_list_size", "3",         # 3 segments in playlist
    "-hls_flags", "delete_segments+independent_segments",
    str(STREAM_DIR / "stream.m3u8")
]

# ================= DATA MODELS =================

class StreamState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    ERROR = "error"
    STOPPING = "stopping"

class ComponentHealth(Enum):
    HEALTHY = "healthy"     # Working normally
    DEGRADED = "degraded"   # Working but with issues
    FAILED = "failed"       # Not working
    UNKNOWN = "unknown"     # Status unknown

@dataclass
class SystemHealth:
    """System health status"""
    ssh_connection: ComponentHealth = ComponentHealth.UNKNOWN
    pi_camera: ComponentHealth = ComponentHealth.UNKNOWN
    ffmpeg: ComponentHealth = ComponentHealth.UNKNOWN
    http_server: ComponentHealth = ComponentHealth.UNKNOWN
    hls_output: ComponentHealth = ComponentHealth.UNKNOWN
    last_check: float = 0.0
    
    def all_healthy(self) -> bool:
        """Check if all critical components are healthy"""
        return all([
            self.ssh_connection == ComponentHealth.HEALTHY,
            self.pi_camera == ComponentHealth.HEALTHY,
            self.ffmpeg == ComponentHealth.HEALTHY,
            self.http_server == ComponentHealth.HEALTHY,
        ])

@dataclass 
class StreamStats:
    """Streaming statistics"""
    start_time: Optional[float] = None
    duration: float = 0.0
    segments_generated: int = 0
    last_segment_time: float = 0.0
    ffmpeg_restarts: int = 0
    ssh_restarts: int = 0

# ================= HTTP SERVER =================

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded HTTP server for better performance"""
    daemon_threads = True

class QuietHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that doesn't log every request"""
    def log_message(self, format, *args):
        # Only log errors
        if "404" in format % args or "500" in format % args:
            super().log_message(format, *args)
    
    def translate_path(self, path):
        # Serve from stream directory
        return str(STREAM_DIR / path.lstrip('/'))

# ================= CORE ENGINE =================

class HalStreamEngine:
    """Main streaming engine based on 100% working code"""
    
    def __init__(self, use_mqtt: bool = True):
        self.state = StreamState.IDLE
        self.health = SystemHealth()
        self.stats = StreamStats()
        
        # Processes
        self.ssh_process: Optional[subprocess.Popen] = None
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self.http_server: Optional[ThreadedHTTPServer] = None
        self.http_thread: Optional[threading.Thread] = None
        
        # Threading
        self.lock = threading.RLock()
        self.running = True
        self.watchdog_thread: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None
        
        # MQTT
        self.use_mqtt = use_mqtt
        self.mqtt_client: Optional[mqtt.Client] = None
        
        # Event logging
        self.events = deque(maxlen=50)
        self.last_event_time = time.time()
        
        # Feature flags (from original UI)
        self.features = {
            "motion_detection": False,
            "auto_record": False,
            "manual_record": False,
        }
        
        # Initialize
        self._cleanup_old_files()
        self._setup_signal_handlers()
    
    # ================= INITIALIZATION =================
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(sig, frame):
            self.log(f"Signal {sig} received, shutting down...")
            self.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def _cleanup_old_files(self):
        """Clean up old stream files"""
        for ext in ['*.ts', '*.m3u8', '*.tmp']:
            for f in STREAM_DIR.glob(ext):
                try:
                    f.unlink()
                except:
                    pass
    
    # ================= LOGGING =================
    
    def log(self, message: str, level: str = "INFO"):
        """Unified logging"""
        timestamp = time.strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {level}: {message}"
        
        print(log_msg, flush=True)
        self.events.append(log_msg)
        
        # Publish to MQTT if enabled
        if self.use_mqtt and self.mqtt_client:
            try:
                self.mqtt_client.publish(
                    f"{BASE_TOPIC}/log",
                    json.dumps({
                        "time": timestamp,
                        "level": level,
                        "message": message
                    }),
                    retain=False
                )
            except:
                pass
    
    def _publish_status(self):
        """Publish current status to MQTT"""
        if not self.use_mqtt or not self.mqtt_client:
            return
        
        status = {
            "state": self.state.value,
            "health": {k: v.value for k, v in asdict(self.health).items()},
            "stats": asdict(self.stats),
            "features": self.features,
            "timestamp": time.time(),
            "stream_url": f"http://{self._get_local_ip()}:{HTTP_PORT}/stream.m3u8",
            "events": list(self.events)[-5:]  # Last 5 events
        }
        
        try:
            self.mqtt_client.publish(
                T_STATUS,
                json.dumps(status, ensure_ascii=False),
                retain=True
            )
        except Exception as e:
            print(f"Failed to publish status: {e}")
    
    # ================= HEALTH CHECKS =================
    
    def _get_local_ip(self) -> str:
        """Get local IP address for stream URL"""
        try:
            # Try Tailscale first
            result = subprocess.run(
                "tailscale ip --4 2>/dev/null || hostname -I | awk '{print $1}'",
                shell=True,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        except:
            return "127.0.0.1"
    
    def _check_ssh_connection(self) -> bool:
        """Check SSH connection to Pi"""
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", 
                 PI_HOST, "echo SSH_OK"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and "SSH_OK" in result.stdout
        except:
            return False
    
    def _check_http_server(self) -> bool:
        """Check if HTTP server is responding"""
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", "-m", "2", 
                 f"http://127.0.0.1:{HTTP_PORT}/"],
                capture_output=True,
                timeout=3
            )
            return result.returncode == 0
        except:
            return False
    
    def _check_hls_playlist(self) -> bool:
        """Check if HLS playlist exists and is recent"""
        playlist = STREAM_DIR / "stream.m3u8"
        if not playlist.exists():
            return False
        
        try:
            # Check if playlist is being updated
            mtime = playlist.stat().st_mtime
            if time.time() - mtime < 10.0:  # Updated in last 10 seconds
                # Also check content
                content = playlist.read_text()
                return ".ts" in content
            return False
        except:
            return False
    
    def _perform_health_check(self):
        """Perform comprehensive health check"""
        with self.lock:
            # SSH Connection
            ssh_ok = self._check_ssh_connection()
            self.health.ssh_connection = (
                ComponentHealth.HEALTHY if ssh_ok else ComponentHealth.FAILED
            )
            
            # HTTP Server
            http_ok = self._check_http_server()
            self.health.http_server = (
                ComponentHealth.HEALTHY if http_ok else ComponentHealth.FAILED
            )
            
            # HLS Output
            hls_ok = self._check_hls_playlist()
            self.health.hls_output = (
                ComponentHealth.HEALTHY if hls_ok else ComponentHealth.FAILED
            )
            
            # FFmpeg process
            if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                self.health.ffmpeg = ComponentHealth.HEALTHY
            else:
                self.health.ffmpeg = ComponentHealth.FAILED
            
            # Pi Camera (inferred)
            if (self.ssh_process and self.ssh_process.poll() is None and 
                ssh_ok and hls_ok):
                self.health.pi_camera = ComponentHealth.HEALTHY
            else:
                self.health.pi_camera = ComponentHealth.FAILED
            
            self.health.last_check = time.time()
            
            # Update state based on health
            if self.state == StreamState.ACTIVE:
                if not (ssh_ok and http_ok and hls_ok):
                    self.state = StreamState.ERROR
                    self.log("Stream health check failed!", "ERROR")
    
    # ================= STREAM CONTROL =================
    
    def _start_http_server(self):
        """Start HTTP server for HLS"""
        if self.http_server:
            return True
        
        try:
            os.chdir(STREAM_DIR)
            
            # Create and start HTTP server in background thread
            self.http_server = ThreadedHTTPServer(
                ("0.0.0.0", HTTP_PORT),
                QuietHTTPHandler
            )
            
            self.http_thread = threading.Thread(
                target=self.http_server.serve_forever,
                daemon=True
            )
            self.http_thread.start()
            
            # Wait for server to start
            time.sleep(1)
            return self._check_http_server()
            
        except Exception as e:
            self.log(f"Failed to start HTTP server: {e}", "ERROR")
            return False
    
    def start_stream(self) -> bool:
        """Start the stream (100% working method)"""
        with self.lock:
            if self.state == StreamState.ACTIVE:
                self.log("Stream already active")
                return True
            
            self.state = StreamState.STARTING
            self.log("Starting stream...")
            
            # Cleanup old files
            self._cleanup_old_files()
            
            # Start HTTP server
            if not self._start_http_server():
                self.state = StreamState.ERROR
                self.log("Failed to start HTTP server", "ERROR")
                return False
            
            # Stop any existing processes
            self._stop_processes()
            
            try:
                # Step 1: Start SSH connection to Pi
                self.log(f"Connecting to {PI_HOST}...")
                self.ssh_process = subprocess.Popen(
                    ["ssh", PI_HOST, PI_CAM_CMD],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0
                )
                self.stats.ssh_restarts += 1
                
                # Step 2: Start FFmpeg with pipe from SSH
                self.log("Starting FFmpeg HLS...")
                self.ffmpeg_process = subprocess.Popen(
                    FFMPEG_HLS_CMD,
                    stdin=self.ssh_process.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0
                )
                self.stats.ffmpeg_restarts += 1
                
                # Step 3: Wait for stream to become ready
                self.log("Waiting for stream to become ready...")
                start_time = time.time()
                
                while time.time() - start_time < 20:  # 20 second timeout
                    time.sleep(1)
                    
                    if self._check_hls_playlist() and self._check_http_server():
                        self.state = StreamState.ACTIVE
                        self.stats.start_time = time.time()
                        self.stats.last_segment_time = time.time()
                        
                        stream_url = f"http://{self._get_local_ip()}:{HTTP_PORT}/stream.m3u8"
                        self.log(f"✅ Stream ACTIVE: {stream_url}")
                        self._publish_status()
                        return True
                
                # Timeout
                self.log("Stream failed to start (timeout)", "ERROR")
                self._stop_processes()
                self.state = StreamState.ERROR
                return False
                
            except Exception as e:
                self.log(f"Failed to start stream: {e}", "ERROR")
                self._stop_processes()
                self.state = StreamState.ERROR
                return False
    
    def stop_stream(self):
        """Stop the stream"""
        with self.lock:
            if self.state in [StreamState.IDLE, StreamState.STOPPING]:
                return
            
            self.state = StreamState.STOPPING
            self.log("Stopping stream...")
            
            self._stop_processes()
            
            self.state = StreamState.IDLE
            self.stats.start_time = None
            
            self.log("Stream stopped")
            self._publish_status()
    
    def _stop_processes(self):
        """Stop all running processes"""
        # Stop FFmpeg
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=3)
            except:
                try:
                    self.ffmpeg_process.kill()
                except:
                    pass
            finally:
                self.ffmpeg_process = None
        
        # Stop SSH
        if self.ssh_process:
            try:
                self.ssh_process.terminate()
                self.ssh_process.wait(timeout=2)
            except:
                try:
                    self.ssh_process.kill()
                except:
                    pass
            finally:
                self.ssh_process = None
        
        # Kill any remaining camera processes on Pi
        try:
            subprocess.run(
                ["ssh", "-o", "ConnectTimeout=2", PI_HOST,
                 "pkill -9 rpicam-vid 2>/dev/null || true"],
                capture_output=True
            )
        except:
            pass
    
    # ================= FEATURES =================
    
    def take_photo(self) -> bool:
        """Take a photo from the stream"""
        if self.state != StreamState.ACTIVE:
            self.log("Cannot take photo - stream not active", "WARNING")
            return False
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        photo_path = SNAPSHOT_DIR / f"photo_{timestamp}.jpg"
        
        try:
            # Capture frame from HLS stream
            cmd = [
                "ffmpeg", "-loglevel", "error", "-y",
                "-i", f"http://127.0.0.1:{HTTP_PORT}/stream.m3u8",
                "-frames:v", "1",
                "-q:v", "2",  # Quality 1-31 (lower is better)
                str(photo_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and photo_path.exists():
                self.log(f"📸 Photo saved: {photo_path}")
                return True
            else:
                self.log(f"Failed to take photo: {result.stderr}", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"Photo capture error: {e}", "ERROR")
            return False
    
    def start_recording(self) -> bool:
        """Start recording video"""
        if self.state != StreamState.ACTIVE:
            self.log("Cannot record - stream not active", "WARNING")
            return False
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        record_path = RECORD_DIR / f"recording_{timestamp}.mp4"
        
        try:
            # Start recording using separate pipeline
            ssh_record = subprocess.Popen(
                ["ssh", PI_HOST, PI_CAM_CMD],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            cmd = [
                "ffmpeg", "-loglevel", "error", "-y",
                "-fflags", "+genpts",
                "-f", "h264",
                "-i", "pipe:0",
                "-c:v", "copy",
                "-f", "mp4",
                "-movflags", "+faststart",
                str(record_path)
            ]
            
            record_process = subprocess.Popen(
                cmd,
                stdin=ssh_record.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            
            # Store for later stop
            self.recording_process = record_process
            self.recording_ssh = ssh_record
            self.features["manual_record"] = True
            
            self.log(f"🎬 Recording started: {record_path}")
            return True
            
        except Exception as e:
            self.log(f"Failed to start recording: {e}", "ERROR")
            return False
    
    def stop_recording(self):
        """Stop recording"""
        if hasattr(self, 'recording_process'):
            try:
                self.recording_process.terminate()
                self.recording_process.wait(timeout=3)
            except:
                pass
            
            if hasattr(self, 'recording_ssh'):
                try:
                    self.recording_ssh.terminate()
                    self.recording_ssh.wait(timeout=2)
                except:
                    pass
            
            self.features["manual_record"] = False
            self.log("Recording stopped")
    
    # ================= MONITORING =================
    
    def _watchdog_loop(self):
        """Watchdog thread for monitoring stream health"""
        while self.running:
            try:
                # Perform health check every 5 seconds
                self._perform_health_check()
                
                # Auto-restart if in ERROR state and was previously ACTIVE
                if (self.state == StreamState.ERROR and 
                    self.stats.start_time and 
                    time.time() - self.stats.start_time > 30):
                    
                    self.log("Auto-restarting stream after error...")
                    self.stop_stream()
                    time.sleep(2)
                    self.start_stream()
                
                # Publish status regularly
                self._publish_status()
                
                time.sleep(5)
                
            except Exception as e:
                self.log(f"Watchdog error: {e}", "ERROR")
                time.sleep(10)
    
    def _monitor_stream_stats(self):
        """Monitor stream statistics"""
        while self.running:
            try:
                if self.state == StreamState.ACTIVE and self.stats.start_time:
                    # Update duration
                    self.stats.duration = time.time() - self.stats.start_time
                    
                    # Count TS segments
                    ts_files = list(STREAM_DIR.glob("*.ts"))
                    self.stats.segments_generated = len(ts_files)
                    
                    # Update last segment time
                    if ts_files:
                        latest = max(ts_files, key=lambda f: f.stat().st_mtime)
                        self.stats.last_segment_time = latest.stat().st_mtime
                
                time.sleep(2)
                
            except Exception as e:
                self.log(f"Monitor error: {e}", "ERROR")
                time.sleep(5)
    
    # ================= MQTT HANDLING =================
    
    def _setup_mqtt(self):
        """Setup MQTT client and callbacks"""
        if not self.use_mqtt:
            return
        
        self.mqtt_client = mqtt.Client()
        
        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                self.log("Connected to MQTT broker")
                client.subscribe(T_CMD)
                self._publish_status()
            else:
                self.log(f"MQTT connection failed: {rc}", "ERROR")
        
        def on_message(client, userdata, msg):
            try:
                cmd = msg.payload.decode("utf-8").strip().lower()
                self.log(f"MQTT command: {cmd}")
                
                # Handle commands
                if cmd == "stream_on":
                    self.start_stream()
                elif cmd == "stream_off":
                    self.stop_stream()
                elif cmd == "photo":
                    self.take_photo()
                elif cmd == "rec_on":
                    self.start_recording()
                elif cmd == "rec_off":
                    self.stop_recording()
                elif cmd == "motion_on":
                    self.features["motion_detection"] = True
                    self._publish_status()
                elif cmd == "motion_off":
                    self.features["motion_detection"] = False
                    self._publish_status()
                elif cmd == "rec_motion_on":
                    self.features["auto_record"] = True
                    self._publish_status()
                elif cmd == "rec_motion_off":
                    self.features["auto_record"] = False
                    self._publish_status()
                elif cmd == "diag":
                    self._publish_diagnostics()
                elif cmd == "status":
                    self._publish_status()
                
            except Exception as e:
                self.log(f"Error handling MQTT command: {e}", "ERROR")
        
        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_message = on_message
        
        # Connect
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            self.log(f"Failed to connect to MQTT: {e}", "ERROR")
    
    def _publish_diagnostics(self):
        """Publish detailed diagnostics"""
        if not self.use_mqtt or not self.mqtt_client:
            return
        
        diag = {
            "timestamp": time.time(),
            "state": self.state.value,
            "health": {k: v.value for k, v in asdict(self.health).items()},
            "stats": asdict(self.stats),
            "processes": {
                "ssh": self.ssh_process.poll() is None if self.ssh_process else False,
                "ffmpeg": self.ffmpeg_process.poll() is None if self.ffmpeg_process else False,
                "http_server": self.http_server is not None
            },
            "system": {
                "ssh_available": self._check_ssh_connection(),
                "http_responding": self._check_http_server(),
                "hls_active": self._check_hls_playlist(),
                "stream_url": f"http://{self._get_local_ip()}:{HTTP_PORT}/stream.m3u8"
            },
            "features": self.features,
            "events": list(self.events)[-10:]
        }
        
        try:
            self.mqtt_client.publish(
                T_HEALTH,
                json.dumps(diag, indent=2, ensure_ascii=False),
                retain=True
            )
        except:
            pass
    
    # ================= PUBLIC API =================
    
    def start(self):
        """Start the engine"""
        self.log("=" * 60)
        self.log("HAL Stream Engine - FINAL VERSION")
        self.log("Based on 100% working stream_live_deepseek_2.py")
        self.log("=" * 60)
        
        # Start MQTT
        if self.use_mqtt:
            self._setup_mqtt()
        
        # Start monitoring threads
        self.watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True
        )
        self.monitor_thread = threading.Thread(
            target=self._monitor_stream_stats,
            daemon=True
        )
        
        self.watchdog_thread.start()
        self.monitor_thread.start()
        
        self.log("Engine started successfully")
        self.log("Ready for commands. Use MQTT or start stream manually.")
    
    def stop(self):
        """Stop the engine"""
        self.log("Stopping engine...")
        self.running = False
        
        # Stop stream
        self.stop_stream()
        
        # Stop HTTP server
        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except:
                pass
        
        # Stop MQTT
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except:
                pass
        
        self.log("Engine stopped")

# ================= SIMPLE CLI =================

def simple_cli():
    """Simple command-line interface for testing"""
    engine = HalStreamEngine(use_mqtt=False)
    engine.start()
    
    print("\n" + "="*60)
    print("Simple CLI Controls:")
    print("  [1] Start stream")
    print("  [2] Stop stream")
    print("  [3] Take photo")
    print("  [4] Start recording")
    print("  [5] Stop recording")
    print("  [d] Diagnostics")
    print("  [q] Quit")
    print("="*60 + "\n")
    
    try:
        while True:
            cmd = input("> ").strip().lower()
            
            if cmd == '1':
                engine.start_stream()
            elif cmd == '2':
                engine.stop_stream()
            elif cmd == '3':
                engine.take_photo()
            elif cmd == '4':
                engine.start_recording()
            elif cmd == '5':
                engine.stop_recording()
            elif cmd == 'd':
                engine._publish_diagnostics()
                print("Diagnostics printed to logs")
            elif cmd == 'q':
                break
            else:
                print("Unknown command")
                
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        engine.stop()

# ================= MAIN =================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="HAL Stream Engine")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    parser.add_argument("--no-mqtt", action="store_true", help="Disable MQTT")
    parser.add_argument("--auto-start", action="store_true", help="Auto-start stream")
    
    args = parser.parse_args()
    
    if args.cli:
        simple_cli()
        return
    
    # Create and start engine
    engine = HalStreamEngine(use_mqtt=not args.no_mqtt)
    engine.start()
    
    # Auto-start if requested
    if args.auto_start:
        print("Auto-starting stream...")
        engine.start_stream()
    
    # Keep main thread alive
    try:
        while engine.running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        engine.stop()

if __name__ == "__main__":
    main()
