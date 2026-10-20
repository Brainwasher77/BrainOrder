"""Servidor local (solo 127.0.0.1) para escuchar una vista previa de tus archivos dentro de BrainOrder.

Solo entrega archivos de audio que estén dentro de tus carpetas de música (la de playlists, la de
descargas y tus carpetas de música de Ajustes), y solo a quien tenga la clave de esta sesión.
Acepta pedidos por rangos (Range) para que el reproductor pueda adelantar sin leer todo el archivo.
"""
import mimetypes
import os
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import AUDIO_EXT

TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".mp4": "audio/mp4", ".wav": "audio/wav",
         ".aif": "audio/aiff", ".aiff": "audio/aiff", ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg",
         ".alac": "audio/mp4"}

_STATE = {"server": None, "port": None, "key": secrets.token_urlsafe(16), "roots": lambda: []}
_LOCK = threading.Lock()


def _allowed(path):
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return False
    if p.suffix.lower() not in AUDIO_EXT or not p.is_file():
        return False
    for r in _STATE["roots"]() or []:
        try:
            rr = Path(r).resolve()
        except (OSError, ValueError):
            continue
        if p == rr or rr in p.parents:
            return True
    return False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if (q.get("k") or [""])[0] != _STATE["key"]:
            self.send_error(403)
            return
        path = (q.get("p") or [""])[0]
        if not _allowed(path):
            self.send_error(404)
            return
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                if a:
                    start, end = int(a), (int(b) if b else size - 1)
                else:
                    start = max(0, size - int(b))
            except ValueError:
                start, end = 0, size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        ext = Path(path).suffix.lower()
        self.send_header("Content-Type", TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # el reproductor cortó (adelantaste o cerraste): normal


def start(roots):
    """roots: función que devuelve las carpetas permitidas (se lee en cada pedido: sigue a tus Ajustes)."""
    with _LOCK:
        _STATE["roots"] = roots
        if _STATE["server"] is None:
            srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True, name="vista-previa").start()
            _STATE["server"], _STATE["port"] = srv, srv.server_address[1]
    return _STATE["port"]


def url_for(path):
    return (f"http://127.0.0.1:{_STATE['port']}/a?k={_STATE['key']}&p=" + urllib.parse.quote(str(path)))
