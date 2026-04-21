# camera/http_server.py
# ETAP 4 – serwer HTTP do serwowania katalogu HLS (bez os.chdir)

import os
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from typing import Optional


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


class HLSHttpServer:
    def __init__(self, bind: str, port: int, directory: str):
        self.bind = bind
        self.port = port
        self.directory = directory

        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

        self.ready = threading.Event()
        self.running = threading.Event()
        self._lock = threading.RLock()

    def is_running(self) -> bool:
        return self.running.is_set()

    def start(self) -> bool:
        with self._lock:
            if self.running.is_set():
                return True

            self.ready.clear()
            self.running.clear()

            def _worker():
                try:
                    os.makedirs(self.directory, exist_ok=True)

                    handler_cls = self._make_handler(self.directory)
                    ThreadingHTTPServer.allow_reuse_address = True
                    self.httpd = ThreadingHTTPServer((self.bind, self.port), handler_cls)

                    self.running.set()
                    self.ready.set()

                    self.httpd.serve_forever()
                except Exception as e:
                    self.ready.set()
                    try:
                        print(f"[http] start failed: {e!r}", flush=True)
                    except Exception:
                        pass
                finally:
                    self.running.clear()
                    try:
                        if self.httpd:
                            self.httpd.server_close()
                    except Exception:
                        pass
                    self.httpd = None

            self.thread = threading.Thread(target=_worker, daemon=True)
            self.thread.start()

        self.ready.wait(timeout=3.0)
        return self.running.is_set()

    def stop(self):
        with self._lock:
            try:
                if self.httpd:
                    self.httpd.shutdown()
            except Exception:
                pass
            self.running.clear()
            self.httpd = None

    @staticmethod
    def _make_handler(directory: str):
        # kompatybilne z py3.7+ (set directory)
        class _Handler(QuietHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=directory, **kwargs)

            def copyfile(self, source, outputfile):
                try:
                    return super().copyfile(source, outputfile)
                except (BrokenPipeError, ConnectionResetError):
                    return

        return _Handler
