"""Carpetas nuevas dentro de tu carpeta de playlists que todavía no son una playlist.

Cuando creas una carpeta a mano en tu carpeta de playlists (y le pones música), BrainOrder la detecta y
te pregunta si quieres importarla como playlist: en Spotify, solo en BrainOrder y tus programas de DJ,
o como archivo para importar en otra plataforma.

Estado en SUPPORT/carpetas.json:
    known      carpetas que ya existían la primera vez (no se pregunta por ellas, pero aparecen en la lista)
    dismissed  carpetas por las que elegiste «no volver a preguntar»
"""
import json
import os
import threading
from pathlib import Path

import reglas
from config import AUDIO_EXT, SUPPORT_DIR, write_atomic

STATE = SUPPORT_DIR / "carpetas.json"
_LOCK = threading.Lock()
SKIP = {"_duplicados", "_Informes", "_organizadas"}


def _key(p):
    return os.path.normcase(os.path.normpath(str(p)))


def load():
    try:
        d = json.loads(STATE.read_text("utf-8"))
        return {"known": set(d.get("known") or []), "dismissed": set(d.get("dismissed") or []), "ok": True}
    except Exception:
        return {"known": set(), "dismissed": set(), "ok": False}


def save(st):
    with _LOCK:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(STATE, json.dumps({"known": sorted(st["known"]), "dismissed": sorted(st["dismissed"])},
                                       ensure_ascii=False))


def count_audio(folder, cap=2000):
    n = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        n += sum(1 for f in filenames if not f.startswith(".") and os.path.splitext(f)[1].lower() in AUDIO_EXT)
        if n >= cap:
            break
    return n


def unmatched(cfg, analysis):
    """Subcarpetas de tu carpeta de playlists que no son de ninguna playlist. -> [{path, name}]"""
    root = Path(cfg.get("dest_root") or "")
    if not root.is_dir():
        return []
    ex = reglas.Excluder(reglas.get(cfg))
    used = {_key(p.get("folder")) for p in analysis or [] if p.get("folder")}
    used |= {_key(e.get("path")) for e in cfg.get("folder_playlists") or [] if e.get("path")}
    out = []
    try:
        subs = sorted(d for d in root.iterdir() if d.is_dir())
    except OSError:
        return []
    for d in subs:
        if d.name.startswith((".", "_")) or d.name in SKIP or ex.dir_excluded(str(d)) or _key(d) in used:
            continue
        out.append({"path": str(d), "name": d.name})
    return out


def baseline_if_needed(cfg, analysis):
    """La primera vez: las carpetas que ya existen quedan como conocidas (no se pregunta por todas de golpe)."""
    st = load()
    if st["ok"]:
        return st
    st["known"] = {_key(x["path"]) for x in unmatched(cfg, analysis)}
    save(st)
    st["ok"] = True
    return st


def pending(cfg, analysis, with_counts=True):
    """Carpetas sin playlist (las nuevas primero). Las descartadas para siempre no aparecen."""
    st = baseline_if_needed(cfg, analysis)
    out = []
    for x in unmatched(cfg, analysis):
        k = _key(x["path"])
        if k in st["dismissed"]:
            continue
        x["new"] = k not in st["known"]
        if with_counts:
            x["count"] = count_audio(x["path"])
        out.append(x)
    out.sort(key=lambda x: (not x["new"], x["name"].lower()))
    return out


def mark(path, known=False, dismissed=False):
    st = load()
    if known:
        st["known"].add(_key(path))
    if dismissed:
        st["dismissed"].add(_key(path))
        st["known"].add(_key(path))
    st["ok"] = True
    save(st)


def undismiss(path):
    st = load()
    st["dismissed"].discard(_key(path))
    save(st)
