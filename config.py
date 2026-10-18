"""Configuración y rutas de BrainOrder."""
import copy
import json
import threading
import os
from datetime import datetime
from pathlib import Path

import plataforma

HOME = Path.home()
SUPPORT_DIR = plataforma.support_dir()
CONFIG_FILE = SUPPORT_DIR / "config.json"
TOKEN_FILE = SUPPORT_DIR / "token.json"
LOG_FILE = SUPPORT_DIR / "brainorder.log"

AUDIO_EXT = {".mp3", ".m4a", ".aif", ".aiff", ".wav", ".flac", ".alac", ".ogg", ".aac", ".mp4"}

DEFAULTS = {
    "client_id": "",
    "redirect_uri": "http://127.0.0.1:8888/callback",
    # Carpeta espejo de Spotify: una subcarpeta por playlist
    "dest_root": str(HOME / "Music" / "Playlists BrainOrder"),
    # Bandeja de entrada: donde caen las descargas nuevas
    "inbox": str(HOME / "Music" / "Descargas BrainOrder"),
    # Dónde buscar canciones que ya tienes (además de dest_root e inbox)
    # (vacío en instalaciones nuevas: cada usuario elige las suyas en Ajustes)
    "library_roots": [],
    "liked_name": "Me gusta",
    "include_liked": True,
    # Carpeta de playlists en Rekordbox que replica Spotify
    "rekordbox_folder": "BrainOrder",
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


def _read_saved():
    """Ajustes guardados. Si el archivo se dañó (corte de luz, disco lleno…) se intenta la copia
    anterior y el dañado se aparta con fecha: nunca se reemplazan tus ajustes por los de fábrica sin avisar."""
    bak = CONFIG_FILE.with_name(CONFIG_FILE.name + ".bak")
    if not CONFIG_FILE.exists() and not bak.exists():
        return None
    for f in (CONFIG_FILE, bak):
        try:
            data = json.loads(f.read_text("utf-8"))
            if isinstance(data, dict):
                if f != CONFIG_FILE:
                    log(f"config.json estaba dañado: se recuperó la copia anterior ({f.name})")
                return data
        except Exception:
            continue
    if not CONFIG_FILE.exists():
        return None
    try:
        bad = CONFIG_FILE.with_name(f"config.dañado-{datetime.now():%Y%m%d-%H%M%S}.json")
        os.replace(CONFIG_FILE, bad)
        log(f"config.json dañado y sin copia: se apartó como {bad.name}")
    except OSError:
        pass
    return None


def load():
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(DEFAULTS)  # copia profunda: los ajustes nunca modifican los valores de fábrica
    saved = _read_saved()
    if saved is not None:
        try:
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
    """Guardado atómico y de a uno (varias tareas pueden guardar ajustes a la vez).
    Se escribe a un temporal, se fuerza al disco y se reemplaza; la versión anterior queda como .bak."""
    with _SAVE_LOCK:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        for attempt in range(5):  # otra tarea pudo cambiar un ajuste justo mientras se serializaba
            try:
                data = json.dumps(cfg, indent=2, ensure_ascii=False)
                break
            except RuntimeError:
                if attempt == 4:
                    raise
                import time
                time.sleep(0.02)
        write_atomic(CONFIG_FILE, data, keep_backup=True)


def write_atomic(path, text, keep_backup=False):
    """Escribe un archivo de texto sin que nunca quede a medias (temporal + fsync + reemplazo)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    if keep_backup and path.exists():
        try:
            bak = path.with_name(path.name + ".bak")
            if bak.exists():
                bak.unlink()
            os.link(path, bak)  # copia instantánea (mismo archivo); se libera al reemplazar
        except OSError:
            pass
    os.replace(tmp, path)


def safe_name(name: str) -> str:
    """Nombre de playlist -> nombre de carpeta válido (macOS y Windows)."""
    return plataforma.safe_name(name)


_LOG_LOCK = threading.Lock()
LOG_MAX = 5 * 1024 * 1024  # al pasar de 5 MB se rota (se guarda la anterior como .1)


def log(msg: str):
    try:
        with _LOG_LOCK:
            SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            try:
                if LOG_FILE.stat().st_size > LOG_MAX:
                    os.replace(LOG_FILE, LOG_FILE.with_name(LOG_FILE.name + ".1"))
            except OSError:
                pass
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass
