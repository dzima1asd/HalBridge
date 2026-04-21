#!/usr/bin/env python3
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, asdict
from typing import List, Optional

import paho.mqtt.client as mqtt


BROKER_HOST = os.getenv("MUSIC_MQTT_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("MUSIC_MQTT_PORT", "1883"))
BROKER_USER = os.getenv("MUSIC_MQTT_USER", "")
BROKER_PASS = os.getenv("MUSIC_MQTT_PASS", "")

TOPIC_CMD = os.getenv("MUSIC_TOPIC_CMD", "hal/music/cmd")
TOPIC_REPLY = os.getenv("MUSIC_TOPIC_REPLY", "hal/music/reply")
TOPIC_STATUS = os.getenv("MUSIC_TOPIC_STATUS", "hal/music/status")
TOPIC_CONFIRM = os.getenv("MUSIC_TOPIC_CONFIRM", "hal/music/confirm")
TOPIC_RESULTS = os.getenv("MUSIC_TOPIC_RESULTS", "hal/music/results")
TOPIC_ACK = os.getenv("MUSIC_TOPIC_ACK", "hal/music/ack")
TOPIC_ERROR = os.getenv("MUSIC_TOPIC_ERROR", "hal/music/error")
TOPIC_NOW_PLAYING = os.getenv("MUSIC_TOPIC_NOW_PLAYING", "hal/music/now_playing")

SESSION_TIMEOUT = int(os.getenv("MUSIC_SESSION_TIMEOUT", "180"))
YTDLP_BIN = os.getenv("MUSIC_YTDLP_BIN", "yt-dlp")
MPV_BIN = os.getenv("MUSIC_MPV_BIN", "mpv")


@dataclass
class SearchResult:
    id: int
    title: str
    url: str
    uploader: str = ""
    duration: Optional[int] = None


@dataclass
class Session:
    session_id: str
    query_text: str
    created_at: float
    state: str
    results: List[SearchResult]


class MusicAgent:
    def __init__(self) -> None:
        self.hostname = socket.gethostname()
        self.client = mqtt.Client(client_id=f"music-agent-{self.hostname}")
        if BROKER_USER:
            self.client.username_pw_set(BROKER_USER, BROKER_PASS)

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.current_session: Optional[Session] = None
        self.player_proc: Optional[subprocess.Popen] = None
        self.player_lock = threading.Lock()
        self.current_track: Optional[SearchResult] = None

    def publish(self, topic: str, payload: dict) -> None:
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=0, retain=False)

    def ack(self, text: str, **extra) -> None:
        payload = {"ok": True, "text": text, **extra}
        self.publish(TOPIC_ACK, payload)

    def error(self, text: str, **extra) -> None:
        payload = {"ok": False, "error": text, **extra}
        self.publish(TOPIC_ERROR, payload)

    def status(self, state: str, **extra) -> None:
        payload = {"state": state, **extra}
        self.publish(TOPIC_STATUS, payload)

    def on_connect(self, client, userdata, flags, rc):
        self.client.subscribe(TOPIC_CMD)
        self.client.subscribe(TOPIC_REPLY)
        self.status("online", subscribed=[TOPIC_CMD, TOPIC_REPLY])

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            self.error(f"Nieprawidłowy JSON: {e}", topic=msg.topic)
            return

        try:
            if msg.topic == TOPIC_CMD:
                self.handle_cmd(payload)
            elif msg.topic == TOPIC_REPLY:
                self.handle_reply(payload)
        except Exception as e:
            self.error(f"Błąd obsługi wiadomości: {type(e).__name__}: {e}", topic=msg.topic)

    def handle_cmd(self, payload: dict) -> None:
        text = str(payload.get("text", "")).strip()
        command = str(payload.get("command", "")).strip().lower()

        if command:
            self.handle_control_command(command)
            return

        if not text:
            self.error("Brak pola 'text' lub 'command' w payloadzie.")
            return

        lowered = text.lower().strip()

        if lowered in {"stop", "zatrzymaj", "wyłącz muzykę"}:
            self.stop_player()
            self.ack("Odtwarzanie zatrzymane.")
            self.status("stopped")
            return

        if lowered in {"pauza", "pause"}:
            self.pause_player()
            self.ack("Pauza.")
            self.status("paused")
            return

        if lowered in {"wznów", "resume", "graj dalej"}:
            self.resume_player()
            self.ack("Wznawiam.")
            self.status("playing")
            return

        if lowered in {"status", "co leci", "co teraz leci?"}:
            self.publish_current_status()
            return

        self.handle_search_request(text)

    def handle_control_command(self, command: str) -> None:
        if command == "stop":
            self.stop_player()
            self.ack("Odtwarzanie zatrzymane.")
            self.status("stopped")
        elif command == "pause":
            self.pause_player()
            self.ack("Pauza.")
            self.status("paused")
        elif command == "resume":
            self.resume_player()
            self.ack("Wznawiam.")
            self.status("playing")
        elif command == "status":
            self.publish_current_status()
        else:
            self.error(f"Nieznana komenda sterująca: {command}")

    def handle_search_request(self, text: str) -> None:
        self.status("searching", query=text)

        exclude_artists = self.extract_excluded_artists(text)
        search_query = self.build_search_query(text)

        self.ack("DEBUG query", query=search_query, exclude_artists=exclude_artists)
        self.ack("DEBUG query", query=search_query, exclude_artists=exclude_artists)
        results = self.search_youtube(search_query, limit=3, exclude_artists=exclude_artists)

        if not results:
            self.error("Nie znalazłem sensownych wyników.", query=search_query)
            self.status("idle")
            return

        session_id = f"music_{int(time.time())}"
        self.current_session = Session(
            session_id=session_id,
            query_text=text,
            created_at=time.time(),
            state="awaiting_confirmation",
            results=results,
        )

        self.publish(
            TOPIC_RESULTS,
            {
                "session_id": session_id,
                "query_text": text,
                "results": [asdict(r) for r in results],
            },
        )

        options = [f"{r.id}. {r.title}" for r in results]
        question = f"Znalazłem {len(results)} propozycje. Puścić 1, 2 czy 3?"

        self.publish(
            TOPIC_CONFIRM,
            {
                "session_id": session_id,
                "question": question,
                "options": options,
            },
        )

        self.ack("Wyniki gotowe, czekam na wybór.", session_id=session_id)
        self.status("awaiting_confirmation", session_id=session_id)

    def handle_reply(self, payload: dict) -> None:
        if not self.current_session:
            self.error("Brak aktywnej sesji wyboru.")
            return

        if time.time() - self.current_session.created_at > SESSION_TIMEOUT:
            old_session = self.current_session.session_id
            self.current_session = None
            self.error("Sesja wyboru wygasła.", session_id=old_session)
            self.status("idle")
            return

        session_id = str(payload.get("session_id", "")).strip()
        if session_id and session_id != self.current_session.session_id:
            self.error(
                "session_id nie pasuje do aktywnej sesji.",
                expected=self.current_session.session_id,
                received=session_id,
            )
            return

        choice = payload.get("choice")
        if choice is None:
            text = str(payload.get("text", "")).strip().lower()
            choice = self.parse_choice_from_text(text)

        if not isinstance(choice, int):
            self.error("Nie rozumiem wyboru. Podaj 1, 2 albo 3.")
            return

        chosen = next((r for r in self.current_session.results if r.id == choice), None)
        if not chosen:
            self.error("Wybrana pozycja nie istnieje.", choice=choice)
            return

        self.play_result(chosen, session_id=self.current_session.session_id)
        self.current_session.state = "playing"

    def parse_choice_from_text(self, text: str) -> Optional[int]:
        mapping = {
            "1": 1, "pierwszy": 1, "pierwszą": 1, "jedynka": 1, "jedynkę": 1,
            "2": 2, "drugi": 2, "drugą": 2, "dwójka": 2, "dwójkę": 2,
            "3": 3, "trzeci": 3, "trzecią": 3, "trójka": 3, "trójkę": 3,
        }
        return mapping.get(text)

    def extract_excluded_artists(self, text: str) -> List[str]:
        patterns = [
            r"\bnie\s+(.+?)\b",
            r"\bbez\s+(.+?)\b",
            r"\bz wyjątkiem\s+(.+?)\b",
        ]
        excluded = []
        lower = text.lower()

        if "black sabbath" in lower:
            excluded.append("Black Sabbath")

        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                value = match.group(1).strip(" .,!?:;")
                if value:
                    excluded.append(value)

        clean = []
        for item in excluded:
            item = item.strip()
            if item and item not in clean:
                clean.append(item)
        return clean

    def build_search_query(self, text: str) -> str:
        lower = text.lower().strip()

        genre = ""
        era = ""
        extras = []

        if "heavy metal" in lower:
            genre = "heavy metal"
        elif "doom metal" in lower:
            genre = "doom metal"
        elif "metal" in lower:
            genre = "metal"

        if "70" in lower or "70tych" in lower or "70-tych" in lower or "lat 70" in lower:
            era = "1970s"

        if "live" in lower:
            extras.append("live")
        else:
            extras.append("song")

        query_parts = []

        if genre:
            query_parts.append(genre)
        if era:
            query_parts.append(era)

        query_parts += ["classic", "full song"]

        query = " ".join(query_parts).strip()
        return query

    def search_youtube(self, query: str, limit: int = 3, exclude_artists: Optional[List[str]] = None) -> List[SearchResult]:
        exclude_artists = exclude_artists or []
        search_expr = f"ytsearch15:{query}"

        cmd = [
            YTDLP_BIN,
            "--dump-single-json",
            "--no-warnings",
            "--flat-playlist",
            search_expr,
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "yt-dlp zwrócił błąd")

        data = json.loads(proc.stdout)
        entries = data.get("entries", []) or []

        results: List[SearchResult] = []
        next_id = 1

        for entry in entries:
            title = str(entry.get("title", "")).strip()
            title_l = title.lower()

            bad_phrases = [
                "mix", "playlist", "compilation", "best of", "full album",
                "greatest hits", "hour", "hours", "2020", "2021", "2022",
                "2023", "2024", "2025", "2026"
            ]

            if any(x in title_l for x in bad_phrases):
                continue
            video_id = str(entry.get("id", "")).strip()
            uploader = str(entry.get("uploader", "")).strip()
            duration = entry.get("duration")

            if not title or not video_id:
                continue

            haystack = f"{title} {uploader}".lower()
            skip = False
            for artist in exclude_artists:
                if artist.lower() in haystack:
                    skip = True
                    break
            if skip:
                continue

            url = f"https://www.youtube.com/watch?v={video_id}"
            results.append(
                SearchResult(
                    id=next_id,
                    title=title,
                    url=url,
                    uploader=uploader,
                    duration=duration if isinstance(duration, int) else None,
                )
            )
            next_id += 1

            if len(results) >= limit:
                break

        return results

    def play_result(self, result: SearchResult, session_id: str) -> None:
        self.stop_player()

        cmd = [
            MPV_BIN,
            "--force-window=yes",
            "--title=HAL Music Agent",
            result.url,
        ]

        with self.player_lock:
            self.player_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
            self.current_track = result

        self.publish(
            TOPIC_NOW_PLAYING,
            {
                "session_id": session_id,
                "title": result.title,
                "url": result.url,
                "uploader": result.uploader,
                "duration": result.duration,
            },
        )

        self.ack("Uruchamiam odtwarzanie.", title=result.title, session_id=session_id)
        self.status("playing", title=result.title, session_id=session_id)

    def stop_player(self) -> None:
        with self.player_lock:
            if self.player_proc and self.player_proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self.player_proc.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            self.player_proc = None
            self.current_track = None

    def pause_player(self) -> None:
        with self.player_lock:
            if self.player_proc and self.player_proc.poll() is None:
                os.kill(self.player_proc.pid, signal.SIGSTOP)

    def resume_player(self) -> None:
        with self.player_lock:
            if self.player_proc and self.player_proc.poll() is None:
                os.kill(self.player_proc.pid, signal.SIGCONT)

    def publish_current_status(self) -> None:
        with self.player_lock:
            alive = self.player_proc is not None and self.player_proc.poll() is None

        if alive and self.current_track:
            self.publish(
                TOPIC_STATUS,
                {
                    "state": "playing",
                    "title": self.current_track.title,
                    "url": self.current_track.url,
                    "uploader": self.current_track.uploader,
                },
            )
            self.ack(f"Teraz leci: {self.current_track.title}")
        else:
            self.publish(TOPIC_STATUS, {"state": "idle"})
            self.ack("Nic teraz nie leci.")

    def run(self) -> None:
        self.client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        self.client.loop_forever()


if __name__ == "__main__":
    agent = MusicAgent()
    agent.run()
