"""Configuración y rutas de SpotiSync."""
import json
import threading
import os
from pathlib import Path

import plataforma

HOME = Path.home()
SUPPORT_DIR = plataforma.support_dir()
CONFIG_FILE = SUPPORT_DIR / "config.json"
TOKEN_FILE = SUPPORT_DIR / "token.json"
LOG_FILE = SUPPORT_DIR / "spotisync.log"

AUDIO_EXT = {".mp3", ".m4a", ".aif", ".aiff", ".wav", ".flac", ".alac", ".ogg", ".aac", ".mp4"}

DEFAULTS = {
    "client_id": "",
    "redirect_uri": "http://127.0.0.1:8888/callback",
    # Carpeta espejo de Spotify: una subcarpeta por playlist
    "dest_root": str(HOME / "Music" / "Playlists SpotiSync"),
    # Bandeja de entrada: donde caen las descargas nuevas
    "inbox": str(HOME / "Music" / "Descargas SpotiSync"),
    # Dónde buscar canciones que ya tienes (además de dest_root e inbox)
    # (vacío en instalaciones nuevas: cada usuario elige las suyas en Ajustes)
    "library_roots": [],
    "liked_name": "Me gusta",
    "include_liked": True,
    # Carpeta de playlists en Rekordbox que replica Spotify
    "rekordbox_folder": "Spotify",
    # Subcarpeta dentro de la bandeja a donde van los originales ya organizados
    "inbox_done": "_organizadas",
    # Fuentes de playlists y programas de DJ (pantalla Conexiones)
    "sources": {"spotify": {"enabled": True},
                "deezer": {"enabled": False, "user": "", "playlists": [], "include_loved": True},
                "archivos": {"enabled": False, "folder": ""}},
    "destinations": {"rekordbox": {"enabled": True},
                     "traktor": {"enabled": False, "nml": ""},
                     "m3u": {"enabled": False, "folder": ""}},
    # Playlists que no son tuyas: {id: {"name","owner","url","choice": "integrar"|"no"}}
    "foreign": {},
}


def load():
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text("utf-8"))
            if "setup_done" not in saved:  # quien ya venía usando la app no necesita el asistente
                saved["setup_done"] = bool(saved.get("client_id") or saved.get("sources"))
            if "library_roots" not in saved:  # instalaciones viejas: conservar lo que venía antes
                saved["library_roots"] = [str(HOME / "Music" / n) for n in
                                          ("DJ Library", "Playlists rekordbox", "deemix Music")
                                          if (HOME / "Music" / n).is_dir()]
            cfg.update(saved)
        except Exception:
            pass
    return cfg


_SAVE_LOCK = threading.Lock()


def save(cfg):
    """Guardado atómico y de a uno (varias tareas pueden guardar ajustes a la vez)."""
    with _SAVE_LOCK:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        data = json.dumps(cfg, indent=2, ensure_ascii=False)
        tmp = CONFIG_FILE.with_name(f".{CONFIG_FILE.name}.tmp")
        tmp.write_text(data, "utf-8")
        os.replace(tmp, CONFIG_FILE)


def safe_name(name: str) -> str:
    """Nombre de playlist -> nombre de carpeta válido (macOS y Windows)."""
    return plataforma.safe_name(name)


def log(msg: str):
    try:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass
