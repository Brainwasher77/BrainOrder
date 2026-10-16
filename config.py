"""Configuración y rutas de SpotiSync."""
import json
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
    "dest_root": str(HOME / "Music" / "Spotify playlists"),
    # Bandeja de entrada: donde caen las descargas nuevas
    "inbox": str(HOME / "Music" / "descargas para organizar"),
    # Dónde buscar canciones que ya tienes (además de dest_root e inbox)
    "library_roots": [
        str(HOME / "Music" / "DJ Library"),
        str(HOME / "Music" / "Playlists rekordbox"),
        str(HOME / "Music" / "deemix Music"),
    ],
    "liked_name": "Me gusta",
    "include_liked": True,
    # Carpeta de playlists en Rekordbox que replica Spotify
    "rekordbox_folder": "Spotify",
    # Subcarpeta dentro de la bandeja a donde van los originales ya organizados
    "inbox_done": "_organizadas",
    # Playlists que no son tuyas: {id: {"name","owner","url","choice": "integrar"|"no"}}
    "foreign": {},
}


def load():
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg):
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")


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
