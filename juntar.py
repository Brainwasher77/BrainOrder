"""Juntar toda tu música en tu carpeta de playlists (BRAIN LIBRARY).

Hasta ahora, una canción que ya tenías en «otras carpetas de música» (Playlists rekordbox, DJ Library…) se
usaba donde estaba («ya la tienes en otra carpeta») y nunca se movía. Aquí, para las carpetas que elijas:
  - cada canción que está en alguna playlist va a su carpeta hogar (la de su playlist según tu prioridad,
    también las de subcarpetas: Brainwasher/Soft/…, Crossover/ADC/…);
  - la que no está en ninguna playlist va a «_Sin Playlist» (para que decidas después);
  - si en el destino (o, para las que no tienen playlist, en cualquier parte de tu carpeta) ya hay una canción
    con el mismo nombre, es una repetida: la de afuera va a _duplicados y se anota cuál se queda (dup_of).
    Pedido de Frank (2.50.1): no quiere copias «Canción (2)» aunque duren distinto. Nunca se pisa ni se borra
    nada (lo de _duplicados se puede recuperar o vaciar después).
Los accesos directos y la carpeta vacía se resuelven después con lo de accesos.py (app.gather_run).
Aquí solo se calcula (sin mover nada), para poder probarlo.
"""
import os
import unicodedata
from pathlib import Path

from config import AUDIO_EXT

JUNK = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}


def _k(p):
    return os.path.normcase(unicodedata.normalize("NFC", os.path.normpath(str(p))))


def inside(child, parent):
    c, p = _k(child), _k(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def audio_files(root):
    """Audio de verdad dentro de root (no accesos directos, ni ocultos, ni lo que ya está en _duplicados)."""
    out = []
    for d, ds, fs in os.walk(root):
        ds[:] = sorted(x for x in ds if not x.startswith(".") and x != "_duplicados")
        for f in sorted(fs):
            p = os.path.join(d, f)
            if f.startswith(".") or f in JUNK or os.path.islink(p) or Path(f).suffix.lower() not in AUDIO_EXT:
                continue
            if os.path.isfile(p):
                out.append(p)
    return out


def plan(analysis, roots, dest_root, nopl_dir, keep_dirs=(), same_recording=None, stem_key=None):
    """-> {"ops": [(src, carpeta destino, nombre nuevo o None)], "dup_of": {src: el que se queda},
           "by_root": {root: {"home", "nopl", "dup", "kept"}}, "homes": {src: carpeta}}
    analysis: el de BrainOrder (filas con source y dest_dir = carpeta hogar de la canción).
    keep_dirs: carpetas de playlists importadas desde esas carpetas (son su hogar: no se tocan).
    same_recording(a, b) -> bool; stem_key(nombre de archivo) -> clave «artista título» para reconocer
    repetidas sin playlist."""
    same_recording = same_recording or (lambda a, b: False)
    stem_key = stem_key or (lambda n: Path(n).stem.casefold())
    dest_root = str(dest_root)
    homes = {}
    for pl in analysis or []:
        if pl.get("pending"):
            continue
        for r in pl.get("tracks") or []:
            src, home = r.get("source"), r.get("dest_dir")
            if src and home and inside(home, dest_root) and not inside(src, dest_root):
                homes.setdefault(_k(src), home)
    # lo que ya tienes en tu carpeta de playlists, por nombre (para reconocer repetidas sin playlist)
    have = {}
    for d, ds, fs in os.walk(dest_root):
        ds[:] = [x for x in ds if not x.startswith(".") and x != "_duplicados"]
        for f in fs:
            if Path(f).suffix.lower() in AUDIO_EXT and not f.startswith("."):
                have.setdefault(stem_key(f), []).append(os.path.join(d, f))
    ops, dup_of, by_root, planned, planned_by = [], {}, {}, set(), {}
    dupdir = os.path.join(dest_root, "_duplicados")
    for root in roots:
        n = by_root.setdefault(str(root), {"home": 0, "nopl": 0, "dup": 0, "kept": 0})
        # lo que esa carpeta ya tenía apartado en su propio _duplicados: al _duplicados de tu carpeta
        # (así la carpeta queda vacía y se puede quitar)
        for d, ds, fs in os.walk(root):
            ds[:] = [x for x in ds if not x.startswith(".")]
            if "_duplicados" not in Path(d).parts or any(inside(d, k) for k in keep_dirs):
                continue
            for f in sorted(fs):
                p = os.path.join(d, f)
                if f.startswith(".") or os.path.islink(p) or Path(f).suffix.lower() not in AUDIO_EXT:
                    continue
                to = os.path.join(dupdir, Path(root).name, os.path.relpath(d, root))
                ops.append((p, to, _free(to, f, planned)))
                n["dup"] += 1
        for src in audio_files(root):
            if any(inside(src, k) for k in keep_dirs):
                n["kept"] += 1
                continue
            name = Path(src).name
            home = homes.get(_k(src))
            if home is None:
                twins = have.get(stem_key(name), [])
                # la misma grabación primero; si no, cualquiera con el mismo nombre (también es repetida)
                twin = next((t for t in twins if same_recording(src, t)), twins[0] if twins else None)
                if twin:
                    ops.append((src, os.path.join(dupdir, "_Sin Playlist"), _free(dupdir + os.sep + "_Sin Playlist", name, planned)))
                    dup_of[src] = twin
                    n["dup"] += 1
                    continue
                dest, kind = str(nopl_dir), "nopl"
            else:
                dest, kind = home, "home"
            target = os.path.join(dest, name)
            if os.path.exists(target) or _k(target) in planned:
                # ya hay una con ese nombre (en el disco o una que entra en esta misma vuelta): repetida
                sub = os.path.join(dupdir, Path(dest).name)
                ops.append((src, sub, _free(sub, name, planned)))
                dup_of[src] = target if os.path.exists(target) else planned_by.get(_k(target), target)
                n["dup"] += 1
                continue
            planned.add(_k(target))
            planned_by[_k(target)] = target
            ops.append((src, dest, None))
            n[kind] += 1
    return {"ops": ops, "dup_of": dup_of, "by_root": by_root, "homes": homes}


def _free(dest, name, planned):
    """Nombre libre en dest («Canción (2).mp3»…) que no esté ni en el disco ni ya elegido. None = el mismo."""
    stem, ext = Path(name).stem, Path(name).suffix
    cand, n = name, 1
    while os.path.exists(os.path.join(dest, cand)) or _k(os.path.join(dest, cand)) in planned:
        n += 1
        cand = f"{stem} ({n}){ext}"
    planned.add(_k(os.path.join(dest, cand)))
    return None if cand == name else cand
