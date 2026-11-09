"""Un solo orden para todo.

Eliges qué orden manda (cfg "rb_master"): el de Rekordbox o el de cada plataforma (Spotify, Deezer, archivo).
Ese orden se usa en BrainOrder, en Rekordbox y tus programas, en Spotify (si manda Rekordbox) y en el disco:
cada carpeta de playlist lleva una lista «_<nombre>.m3u8» con las canciones en ese orden (un archivo no tiene
orden propio dentro de una carpeta; la lista sí, y la abren Finder/VLC/Music/Rekordbox/Traktor…).
"""
import os
import re
from pathlib import Path

from config import CREDIT, log, safe_name

MARK = "#BRAINORDER"


def _k(p):
    k = str(p or "").replace("\\", "/")
    while "//" in k:
        k = k.replace("//", "/")
    return k.casefold() if os.name == "nt" else k


def order_map(baseline):
    """{pid: [rutas en el orden de Rekordbox]} desde la foto de Rekordbox."""
    out = {}
    for b in (baseline or {}).values():
        pid = b.get("pid")
        if pid and b.get("paths") and pid not in out:
            out[pid] = list(b["paths"])
    return out


def apply(result, omap):
    """Ordena las canciones de cada playlist como en Rekordbox. Las que Rekordbox no tiene (faltan por
    descargar, etc.) quedan al final en el orden de la plataforma. "pos" no cambia (es la posición en la
    plataforma y la usan Comparar / Fusionar)."""
    for a in result or []:
        paths = omap.get(a.get("id"))
        if not paths:
            continue
        idx = {}
        for i, p in enumerate(paths):
            idx.setdefault(_k(p), i)
        n = len(paths)
        a["tracks"] = sorted(a["tracks"], key=lambda r: (idx.get(_k(r.get("source")), n) if r.get("source") else n,
                                                         r.get("pos", 0)))
        a["order"] = "rekordbox"
    return result


def merge_order(now, ids):
    """Orden nuevo para una playlist de Spotify: primero las de ids (en ese orden, solo las que la playlist
    ya tiene y tantas veces como las tiene), después lo demás como estaba. Nunca agrega ni quita."""
    left = {}
    for i in now:
        left[i] = left.get(i, 0) + 1
    out = []
    for i in ids:
        if left.get(i, 0) > 0:
            out.append(i)
            left[i] -= 1
    for i in now:
        if left.get(i, 0) > 0:
            out.append(i)
            left[i] -= 1
    return out


def wanted_ids(pl):
    """Ids de Spotify de la playlist en el orden común (el de las filas del análisis)."""
    return [r["id"] for r in pl.get("tracks") or [] if re.fullmatch(r"[A-Za-z0-9]{22}", str(r.get("id") or ""))]


def list_name(name):
    return "_" + safe_name(name) + ".m3u8"


def m3u_text(pl, folder, order_label):
    lines = ["#EXTM3U", f"#PLAYLIST:{pl['name']}", f"{MARK} {CREDIT} · orden: {order_label}"]
    seen = set()
    for r in pl.get("tracks") or []:
        src = r.get("source")
        if not src or r.get("status") not in ("ok", "elsewhere") or _k(src) in seen:
            continue
        seen.add(_k(src))
        secs = int((r.get("duration_ms") or 0) / 1000) or -1
        who = ", ".join(r.get("artists") or [])
        lines.append(f"#EXTINF:{secs},{who + ' - ' if who else ''}{r.get('name') or Path(src).stem}")
        try:
            rel = os.path.relpath(src, folder)
        except ValueError:  # otro disco en Windows
            rel = src
        lines.append(rel.replace("\\", "/") if os.name != "nt" else rel)
    return "\n".join(lines) + "\n"


def is_ours(path):
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(400)
        return MARK in head
    except OSError:
        return False


def write_lists(analysis, order_label="la plataforma", only=None):
    """Escribe (o actualiza) la lista ordenada en la carpeta de cada playlist. Solo si cambió; quita las
    listas viejas de BrainOrder que quedaron en esa carpeta con otro nombre. -> cuántas escribió"""
    n = 0
    for pl in analysis or []:
        if only is not None and pl["id"] not in only:
            continue
        folder = pl.get("folder")
        if not folder or pl.get("pending") or pl.get("ignored") or not os.path.isdir(folder):
            continue
        label = "Rekordbox" if pl.get("order") == "rekordbox" else order_label
        txt = m3u_text(pl, folder, label)
        target = Path(folder) / list_name(pl["name"])
        try:
            for old in Path(folder).glob("_*.m3u8"):
                if old.name != target.name and is_ours(old):
                    old.unlink()
            if txt.count("\n") <= 3:  # sin canciones en la carpeta: no hace falta lista
                if target.exists() and is_ours(target):
                    target.unlink()
                continue
            if target.exists() and target.read_text("utf-8") == txt:
                continue
            tmp = target.with_suffix(".tmp")
            tmp.write_text(txt, "utf-8")
            os.replace(tmp, target)
            n += 1
        except OSError as e:
            log(f"lista ordenada de «{pl['name']}»: {e!r}")
    return n


def is_list_file(name):
    return name.startswith("_") and name.lower().endswith(".m3u8")
