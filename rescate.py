"""Canciones que quedaron SOLO en una carpeta `_duplicados` (no hay otra copia en tu música).

«Otra copia» = la misma grabación (plataforma.same_recording): mismo contenido, o mismo nombre y duración, o la
copia que Organizar / Unificar anotaron como «la que se queda» cuando la apartaron (aunque tenga otro nombre).
Es la misma regla con la que se aparta: así lo que se apartó con razón no vuelve a salir aquí como «única copia».

`_duplicados` es para lo repetido: si la vacías, estas se pierden para siempre. Pasa, por ejemplo, cuando
versiones anteriores apartaban una canción cuya «otra copia» era el mismo archivo visto por otro camino
(acceso directo, mayúsculas) o ya no existía. Aquí se encuentran y se devuelven a su lugar:
  1. donde la espera un acceso directo roto (así el acceso directo y Rekordbox vuelven a funcionar solos),
  2. donde estaba antes de que BrainOrder la moviera (Historial),
  3. la carpeta de su playlist (el nombre de la subcarpeta dentro de _duplicados),
  4. si no, <música organizada>/_Recuperadas/<subcarpeta>.
Nunca se pisa nada y todo queda en el Historial (Deshacer).
"""
import os
from collections import defaultdict
from pathlib import Path

import rb_perdidas as RP
from plataforma import _quick_hash, free_name, same_recording

DUP = "_duplicados"
TOL = 4


def _walk(roots):
    """-> (archivos fuera de _duplicados, archivos dentro, accesos directos rotos {nombre: [destino]})"""
    outside, inside, broken, seen = [], [], defaultdict(list), set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for d, ds, fs in os.walk(root):
            ds[:] = [x for x in ds if not x.startswith(".")]
            in_dup = DUP in Path(d).parts
            for f in fs:
                if f.startswith(".") or not f.lower().endswith(RP.AUDIO):
                    continue
                p = os.path.join(d, f)
                k = os.path.normcase(p)
                if k in seen:
                    continue
                seen.add(k)
                if os.path.islink(p) and not os.path.exists(p):
                    t = os.path.normpath(os.path.join(d, os.readlink(p)))
                    broken[os.path.basename(t).lower()].append(t)
                    continue
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                (inside if in_dup else outside).append({"path": p, "size": size, "stem": RP.norm_stem(f)})
    return outside, inside, broken


def _origin(path, moves_back):
    """Dónde estaba justo antes de entrar a _duplicados (Historial). Un solo paso atrás: seguir toda la
    cadena la devolvía a la carpeta de descargas de donde salió la primera vez."""
    return moves_back.get(os.path.normcase(path))


def scan(roots, dest_root, ops=(), duration=None, playlists=()):
    """-> lista de {path, dest, why} para cada canción que solo está en _duplicados."""
    outside, inside, broken = _walk(roots)
    by_size, by_stem = defaultdict(list), defaultdict(list)
    for f in outside:
        by_size[f["size"]].append(f)
        by_stem[f["stem"]].append(f)
    back, original, kept_as = {}, {}, {}
    for op in sorted(ops or [], key=lambda o: o.get("time") or ""):
        if op.get("undone"):
            continue
        for a, b in op.get("moves") or []:
            back[os.path.normcase(b)] = a
            original[os.path.normcase(a)] = a
        for loc, keeper in (op.get("dup_of") or {}).items():  # Organizar/Unificar anotaron cuál copia se quedó
            kept_as[os.path.normcase(loc)] = keeper
    moved_to = {}
    for b, a in back.items():
        moved_to[os.path.normcase(a)] = b
    pl_names = {n.lower(): n for n in playlists or []}
    out, taken = [], set()

    def free(p):
        p = free_name(p)
        while os.path.normcase(str(p)) in taken:
            p = free_name(Path(p).with_name(Path(p).stem + " (2)" + Path(p).suffix))
        return str(p)
    for f in inside:
        twin = None
        for o in by_size.get(f["size"], []):
            try:
                if _quick_hash(o["path"]) == _quick_hash(f["path"]):
                    twin = o["path"]
                    break
            except OSError:
                continue
        if not twin and duration:
            secs = duration(f["path"])
            for o in by_stem.get(f["stem"], []):
                d2 = duration(o["path"])
                if secs and d2 and abs(secs - d2) <= TOL:
                    twin = o["path"]
                    break
        if not twin:
            # la copia que se quedó cuando se apartó (puede tener otro nombre: «Artista feat. X - Canción»)
            k = kept_as.get(os.path.normcase(f["path"]))
            seen_k = set()
            while k and os.path.normcase(k) not in seen_k and not os.path.exists(k):
                seen_k.add(os.path.normcase(k))
                k = moved_to.get(os.path.normcase(k))  # la copia se movió después: se la sigue
            if k and os.path.exists(k) and DUP not in Path(k).parts and same_recording(f["path"], k, duration):
                twin = k
        if twin:
            continue  # sí hay otra copia: es un repetido de verdad
        name = os.path.basename(f["path"])
        dest, why = None, None
        for t in broken.get(name.lower(), []):
            if not os.path.lexists(t) and os.path.normcase(t) not in taken:
                dest, why = t, "donde la espera un acceso directo"
                break
        if not dest:
            o = _origin(f["path"], back)
            if o:
                o = original.get(o, o)
                if DUP not in Path(o).parts and not os.path.lexists(o) and os.path.normcase(o) not in taken:
                    dest, why = o, "donde estaba antes"
        if not dest:
            parts = Path(f["path"]).parts
            i = parts.index(DUP)
            sub = parts[i + 1] if len(parts) > i + 2 else ""
            folder = Path(dest_root) / sub if sub else None
            if folder is not None and (folder.is_dir() or sub.lower() in pl_names):
                dest, why = free(folder / name), f"la carpeta de «{sub}»"
            else:
                dest, why = free(Path(dest_root) / "_Recuperadas" / (sub or "") / name), "_Recuperadas"
        taken.add(os.path.normcase(dest))
        out.append({"path": f["path"], "dest": dest, "why": why, "size": f["size"]})
    return out
