"""Carpetas y playlists nuevas que todavía no son playlist de BrainOrder.

- Carpetas: las que creas dentro de tu carpeta de playlists o de tus carpetas de música (Ajustes),
  aunque estén vacías.
- Programas de DJ: las playlists que creas en Rekordbox, Traktor, Serato o Engine DJ (fuera de la
  carpeta que maneja BrainOrder).
BrainOrder te pregunta si las importa: en Spotify, en otra plataforma (archivo) o solo en BrainOrder.

Estado en SUPPORT/carpetas.json:
    known / dismissed          carpetas conocidas (ya existían) / por las que no quieres que pregunte
    dj_known / dj_dismissed    lo mismo para playlists de programas de DJ ("programa:id")
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


FIELDS = ("known", "dismissed", "dj_known", "dj_dismissed", "dj_programs", "roots")


def load():
    try:
        d = json.loads(STATE.read_text("utf-8"))
        st = {k: set(d.get(k) or []) for k in FIELDS}
        st["ok"] = True
        return st
    except Exception:
        st = {k: set() for k in FIELDS}
        st["ok"] = False
        return st


def save(st):
    with _LOCK:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(STATE, json.dumps({k: sorted(st.get(k) or []) for k in FIELDS}, ensure_ascii=False))


def count_audio(folder, cap=2000):
    n = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        n += sum(1 for f in filenames if not f.startswith(".") and os.path.splitext(f)[1].lower() in AUDIO_EXT)
        if n >= cap:
            break
    return n


def watched_roots(cfg):
    """Carpetas donde se vigilan subcarpetas nuevas: la de playlists y tus carpetas de música (no descargas)."""
    out, seen = [], set()
    inbox = _key(cfg.get("inbox") or "")
    for r in [cfg.get("dest_root")] + list(cfg.get("library_roots") or []):
        if r and Path(r).is_dir() and _key(r) not in seen and _key(r) != inbox:
            seen.add(_key(r))
            out.append(Path(r))
    return out


def unmatched(cfg, analysis):
    """Subcarpetas (directas) de tus carpetas de música que no son de ninguna playlist. -> [{path, name, root}]"""
    ex = reglas.Excluder(reglas.get(cfg))
    used = {_key(p.get("folder")) for p in analysis or [] if p.get("folder")}
    used |= {_key(e.get("path")) for e in cfg.get("folder_playlists") or [] if e.get("path")}
    roots = watched_roots(cfg)
    rootkeys = {_key(r) for r in roots} | {_key(cfg.get("inbox") or "")}
    out = []
    for root in roots:
        try:
            subs = sorted(d for d in root.iterdir() if d.is_dir())
        except OSError:
            continue
        for d in subs:
            if d.name.startswith((".", "_")) or d.name in SKIP or ex.dir_excluded(str(d)) or _key(d) in used \
                    or _key(d) in rootkeys or d.suffix.lower() in (".app", ".musiclibrary", ".photoslibrary"):
                continue
            out.append({"path": str(d), "name": d.name, "root": str(root)})
    return out


def baseline_if_needed(cfg, analysis):
    """Las carpetas que ya existían (la primera vez, o al agregar una carpeta de música en Ajustes) quedan
    como conocidas: no se pregunta por todas de golpe, pero aparecen en la lista."""
    st = load()
    roots = {_key(r) for r in watched_roots(cfg)}
    new_roots = roots - st["roots"] if st["ok"] else roots
    if not new_roots:
        return st
    for x in unmatched(cfg, analysis):
        if _key(x["root"]) in new_roots:
            st["known"].add(_key(x["path"]))
    st["roots"] |= new_roots
    st["ok"] = True
    save(st)
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


# ---------------------------------------------------------------- playlists de programas de DJ
def dj_key(program, ref):
    return f"{program}:{ref}"


def dj_baseline(program, lists):
    """La primera vez que se lee un programa, sus playlists actuales quedan como conocidas."""
    st = load()
    if program in st["dj_programs"]:
        return False
    st["dj_known"] |= {dj_key(program, r) for r in lists}
    st["dj_programs"].add(program)
    st["ok"] = True
    save(st)
    return True


def dj_new(program, lists, imported_keys=()):
    """Playlists del programa que no existían antes, ni descartaste, ni importaste."""
    st = load()
    skip = st["dj_known"] | st["dj_dismissed"] | set(imported_keys)
    return {ref: v for ref, v in lists.items() if dj_key(program, ref) not in skip}


def dj_mark(program, ref, dismissed=False):
    st = load()
    st["dj_known"].add(dj_key(program, ref))
    if dismissed:
        st["dj_dismissed"].add(dj_key(program, ref))
    save(st)


def undismiss(path):
    st = load()
    st["dismissed"].discard(_key(path))
    save(st)
