#!/usr/bin/env python3
"""
Simple HAL Stream UI - Based on 100% working engine
"""

import curses
import time
import json
import threading
from collections import deque

import paho.mqtt.client as mqtt

# ================= CONFIG =================

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
BASE_TOPIC = "hal/stream"

T_CMD = f"{BASE_TOPIC}/cmd"
T_STATUS = f"{BASE_TOPIC}/status"
T_HEALTH = f"{BASE_TOPIC}/health"

# ================= STATE =================

class UIState:
    def __init__(self):
        # Connection
        self.mqtt_connected = False
        self.engine_online = False
        
        # Stream state
        self.stream_active = False
        self.stream_state = "unknown"
        self.stream_url = ""
        
        # Health status
        self.components = {
            "ssh": "⚪",
            "camera": "⚪", 
            "ffmpeg": "⚪",
            "http": "⚪",
            "hls": "⚪"
        }
        
        # Features
        self.recording = False
        self.motion_detection = False
        self.auto_record = False
        
        # Stats
        self.uptime = 0
        self.segments = 0
        self.last_event = ""
        
        # Logs
        self.logs = deque(maxlen=10)
        
        # UI
        self.last_update = time.time()
        self.need_redraw = True

# ================= MQTT =================

class MQTTManager:
    def __init__(self, state: UIState):
        self.state = state
        self.client = mqtt.Client()
        self._setup_callbacks()
    
    def _setup_callbacks(self):
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
    
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.state.mqtt_connected = rc == 0
        if rc == 0:
            client.subscribe(T_STATUS)
            client.subscribe(T_HEALTH)
            # Request initial state
            client.publish(T_CMD, "status")
    
    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.state.mqtt_connected = False
        self.state.engine_online = False
    
    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            
            if msg.topic == T_STATUS:
                self._handle_status(data)
            elif msg.topic == T_HEALTH:
                self._handle_health(data)
                
            self.state.last_update = time.time()
            self.state.need_redraw = True
            
        except json.JSONDecodeError:
            pass
    
    def _handle_status(self, data):
        """Handle status updates"""
        self.state.engine_online = True
        self.state.stream_state = data.get("state", "unknown")
        self.state.stream_active = data.get("state") == "active"
        self.state.stream_url = data.get("stream_url", "")
        
        # Features
        features = data.get("features", {})
        self.state.recording = features.get("manual_record", False)
        self.state.motion_detection = features.get("motion_detection", False)
        self.state.auto_record = features.get("auto_record", False)
        
        # Stats
        stats = data.get("stats", {})
        self.state.uptime = stats.get("duration", 0)
        self.state.segments = stats.get("segments_generated", 0)
        
        # Events
        events = data.get("events", [])
        if events:
            self.state.last_event = events[-1]
    
    def _handle_health(self, data):
        """Handle health updates"""
        health = data.get("health", {})
        
        # Update component status with emojis
        status_map = {
            "healthy": "🟢",
            "degraded": "🟡",
            "failed": "🔴",
            "unknown": "⚪"
        }
        
        self.state.components["ssh"] = status_map.get(
            health.get("ssh_connection", "unknown"), "⚪"
        )
        self.state.components["camera"] = status_map.get(
            health.get("pi_camera", "unknown"), "⚪"
        )
        self.state.components["ffmpeg"] = status_map.get(
            health.get("ffmpeg", "unknown"), "⚪"
        )
        self.state.components["http"] = status_map.get(
            health.get("http_server", "unknown"), "⚪"
        )
        self.state.components["hls"] = status_map.get(
            health.get("hls_output", "unknown"), "⚪"
        )
        
        # Add log
        logs = data.get("events", [])
        if logs:
            for log_entry in logs[-3:]:
                if log_entry not in self.state.logs:
                    self.state.logs.append(log_entry)
    
    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            return True
        except Exception as e:
            print(f"MQTT connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from broker"""
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except:
            pass
    
    def send_command(self, cmd: str):
        """Send command to engine"""
        if self.state.mqtt_connected:
            self.client.publish(T_CMD, cmd)

# ================= UI RENDERER =================

class UIRenderer:
    def __init__(self, stdscr, state: UIState, mqtt: MQTTManager):
        self.stdscr = stdscr
        self.state = state
        self.mqtt = mqtt
        self.init_colors()
    
    def init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Good
        curses.init_pair(2, curses.COLOR_YELLOW, -1)  # Warning
        curses.init_pair(3, curses.COLOR_RED, -1)     # Error
        curses.init_pair(4, curses.COLOR_CYAN, -1)    # Info
        curses.init_pair(5, curses.COLOR_WHITE, -1)   # Normal
    
    def safe_addstr(self, y: int, x: int, text: str, color=0):
        """Safely add string to screen"""
        h, w = self.stdscr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        if x < 0:
            x = 0
        if x + len(text) >= w:
            text = text[:w - x - 1]
        try:
            self.stdscr.addstr(y, x, text, color)
        except:
            pass
    
    def draw(self):
        """Draw the UI"""
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        
        # Colors
        C_GOOD = curses.color_pair(1)
        C_WARN = curses.color_pair(2)
        C_ERROR = curses.color_pair(3)
        C_INFO = curses.color_pair(4)
        C_NORM = curses.color_pair(5)
        
        y = 0
        
        # Header
        self.safe_addstr(y, 0, "🎥 HAL STREAM CONTROLS", C_INFO | curses.A_BOLD)
        
        # Connection status
        conn_status = "🟢 MQTT" if self.state.mqtt_connected else "🔴 MQTT"
        conn_color = C_GOOD if self.state.mqtt_connected else C_ERROR
        self.safe_addstr(y, w - 15, conn_status, conn_color)
        y += 2
        
        # Stream status
        stream_status = "ACTIVE" if self.state.stream_active else "INACTIVE"
        stream_color = C_GOOD if self.state.stream_active else C_ERROR
        self.safe_addstr(y, 0, f"📡 Stream: {stream_status}", stream_color)
        y += 1
        
        # URL
        if self.state.stream_url:
            self.safe_addstr(y, 2, self.state.stream_url, C_INFO)
            y += 1
        
        y += 1
        
        # Component health
        self.safe_addstr(y, 0, "🔧 Component Health:", C_NORM | curses.A_BOLD)
        y += 1
        
        comps = [
            ("SSH", "ssh"),
            ("Camera", "camera"),
            ("FFmpeg", "ffmpeg"),
            ("HTTP", "http"),
            ("HLS", "hls")
        ]
        
        for name, key in comps:
            icon = self.state.components[key]
            self.safe_addstr(y, 2, f"{icon} {name}", C_NORM)
            y += 1
        
        y += 1
        
        # Stats
        if self.state.stream_active:
            uptime_str = time.strftime("%H:%M:%S", time.gmtime(self.state.uptime))
            self.safe_addstr(y, 0, f"⏱️  Uptime: {uptime_str}", C_INFO)
            y += 1
            self.safe_addstr(y, 0, f"📊 Segments: {self.state.segments}", C_INFO)
            y += 1
        
        y += 1
        
        # Features
        self.safe_addstr(y, 0, "⚙️  Features:", C_NORM | curses.A_BOLD)
        y += 1
        
        features = [
            ("🎬 Recording", self.state.recording),
            ("👁️ Motion", self.state.motion_detection),
            ("🧠 Auto-record", self.state.auto_record)
        ]
        
        for name, active in features:
            status = "ON" if active else "OFF"
            color = C_GOOD if active else C_NORM
            self.safe_addstr(y, 2, f"{name}: {status}", color)
            y += 1
        
        y += 1
        
        # Controls
        self.safe_addstr(y, 0, "🎮 Controls:", C_NORM | curses.A_BOLD)
        y += 1
        
        controls = [
            ("1", "Start/Stop Stream"),
            ("2", "Take Photo"),
            ("3", "Start/Stop Record"),
            ("4", "Toggle Motion"),
            ("5", "Toggle Auto-record"),
            ("D", "Diagnostics"),
            ("Q", "Quit")
        ]
        
        for key, desc in controls:
            self.safe_addstr(y, 2, f"[{key}] {desc}", C_INFO)
            y += 1
        
        y += 1
        
        # Last event
        if self.state.last_event:
            self.safe_addstr(y, 0, "📝 Last Event:", C_NORM | curses.A_BOLD)
            y += 1
            self.safe_addstr(y, 2, self.state.last_event[:w-4], C_NORM)
            y += 1
        
        y += 1
        
        # Recent logs
        if self.state.logs:
            self.safe_addstr(y, 0, "📋 Recent Logs:", C_NORM | curses.A_BOLD)
            y += 1
            
            for log_entry in list(self.state.logs)[-3:]:
                # Color code by log level
                if "ERROR" in log_entry:
                    color = C_ERROR
                elif "WARNING" in log_entry:
                    color = C_WARN
                elif "INFO" in log_entry:
                    color = C_INFO
                else:
                    color = C_NORM
                
                self.safe_addstr(y, 2, log_entry[:w-4], color)
                y += 1
                if y >= h - 2:
                    break
        
        # Refresh
        self.stdscr.refresh()
        self.state.need_redraw = False

# ================= APPLICATION =================

class Application:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.state = UIState()
        self.mqtt = MQTTManager(self.state)
        self.renderer = UIRenderer(stdscr, self.state, self.mqtt)
        self.running = True
        
        # Setup curses
        curses.curs_set(0)
        stdscr.timeout(100)
        stdscr.nodelay(True)
    
    def handle_input(self):
        """Handle keyboard input"""
        try:
            key = self.stdscr.getch()
            if key == -1:
                return
            
            char = chr(key).lower()
            
            # Command mapping
            if char == '1':
                cmd = "stream_off" if self.state.stream_active else "stream_on"
                self.mqtt.send_command(cmd)
            elif char == '2':
                self.mqtt.send_command("photo")
            elif char == '3':
                cmd = "rec_off" if self.state.recording else "rec_on"
                self.mqtt.send_command(cmd)
            elif char == '4':
                cmd = "motion_off" if self.state.motion_detection else "motion_on"
                self.mqtt.send_command(cmd)
            elif char == '5':
                cmd = "rec_motion_off" if self.state.auto_record else "rec_motion_on"
                self.mqtt.send_command(cmd)
            elif char == 'd':
                self.mqtt.send_command("diag")
            elif char == 'q':
                self.running = False
            
            self.state.need_redraw = True
            
        except:
            pass
    
    def run(self):
        """Main application loop"""
        # Connect to MQTT
        if not self.mqtt.connect():
            self.state.last_event = "Failed to connect to MQTT"
            self.state.need_redraw = True
        
        # Main loop
        while self.running:
            # Handle input
            self.handle_input()
            
            # Redraw if needed or every 0.5 seconds
            if self.state.need_redraw or time.time() - self.state.last_update > 0.5:
                self.renderer.draw()
            
            # Request status update every 3 seconds
            if (time.time() - self.state.last_update > 3 and 
                self.state.mqtt_connected):
                self.mqtt.send_command("status")
            
            # Small sleep
            time.sleep(0.05)
        
        # Cleanup
        self.mqtt.disconnect()

# ================= MAIN =================

def main(stdscr):
    app = Application(stdscr)
    app.run()

if __name__ == "__main__":
    print("Starting HAL Stream UI...")
    print("Make sure the stream engine is running!")
    print("Press any key to continue...")
    input()
    
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("\nUI terminated by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
