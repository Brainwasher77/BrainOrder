"""Carpetas importadas como playlist: una carpeta dentro de tu carpeta de playlists es una playlist.

Sirve cuando creas una carpeta a mano (y no quieres, o no puedes, crearla en Spotify): BrainOrder la
trata como cualquier otra playlist (estadísticas, faltantes, Rekordbox, Traktor, Serato, Engine…).
Sus canciones son los audios de la carpeta, en orden alfabético.
Ajuste: cfg["folder_playlists"] = [{"name", "path"}].
"""
import hashlib
import os
from pathlib import Path

KEY = "carpetas"
LABEL = "Carpetas"
PREFIX = "dir:"


def entries(cfg):
    return [e for e in cfg.get("folder_playlists") or [] if e.get("path")]


def enabled(cfg):
    return bool(entries(cfg))


def pid_for(path):
    return PREFIX + hashlib.sha1(os.path.normcase(os.path.normpath(str(path))).encode("utf-8")).hexdigest()[:14]


def audio_files(folder, excluder=None):
    """Audios de la carpeta (incluye subcarpetas), en orden alfabético."""
    import biblioteca
    try:
        return sorted(biblioteca.walk_audio(folder, excluder), key=lambda p: p.lower())
    except OSError:
        return []


def _snapshot(files):
    newest = 0
    for f in files:
        try:
            newest = max(newest, int(os.stat(f).st_mtime))
        except OSError:
            pass
    return f"{len(files)}:{newest}"


def list_playlists(cfg, progress=None):
    out = []
    for e in entries(cfg):
        p = Path(e["path"])
        if not p.is_dir():
            continue
        files = audio_files(p)
        out.append({"id": pid_for(p), "name": e.get("name") or p.name, "source": KEY, "snapshot": _snapshot(files),
                    "total": len(files), "url": None})
    return out


def track_for(path):
    """Archivo -> canción con el formato de las demás fuentes."""
    import biblioteca
    p = Path(path)
    artist, title = biblioteca.parse_file(p)
    secs = biblioteca.duration(str(p))
    key = (biblioteca.norm(artist) + "|" + biblioteca.norm(title)).encode("utf-8")
    return {"id": PREFIX + hashlib.sha1(key).hexdigest()[:16], "name": title or p.stem,
            "artists": [artist] if artist else [], "album": "", "duration_ms": int((secs or 0) * 1000),
            "url": "", "isrc": ""}


def tracks(cfg, meta, progress=None):
    e = next((x for x in entries(cfg) if pid_for(x["path"]) == meta["id"]), None)
    if not e:
        return []
    files = audio_files(e["path"])
    out, seen = [], set()
    for n, f in enumerate(files, 1):
        if progress and n % 50 == 0:
            progress(f"Leyendo «{meta['name']}»: {n}/{len(files)}", n / len(files))
        t = track_for(f)
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    return out
