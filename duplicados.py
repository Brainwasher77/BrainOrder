"""Duplicados físicos en TODA tu música (playlists, descargas y demás carpetas de Ajustes).

Dos tipos:
  - «idénticos»: el mismo archivo copiado (mismo tamaño y mismo contenido).
  - «misma canción»: mismo artista, título y versión, con la misma duración (±tolerancia de Reglas),
    aunque sean archivos distintos (otro formato, otra calidad).
Para cada grupo se sugiere cuál conservar: el que tiene cues/playlists en Rekordbox, el analizado
con Mixed In Key, el que usan tus playlists, y luego la mejor calidad según Reglas.
Nada se borra: lo que apartes va a <música organizada>/_duplicados (con Historial para deshacer).
"""
import hashlib
import os
from collections import defaultdict
from pathlib import Path

import armonia
import biblioteca as b
import reglas

try:
    import mutagen
except Exception:  # pragma: no cover
    mutagen = None


def _quick_hash(path, chunk=262144):
    """Huella rápida: tamaño + inicio + final del archivo (suficiente para copias exactas)."""
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            h.update(f.read(chunk))
            if size > chunk * 2:
                f.seek(-chunk, os.SEEK_END)
                h.update(f.read(chunk))
        return f"{size}:{h.hexdigest()}"
    except OSError:
        return None


def _bitrate(path):
    if not mutagen:
        return None
    try:
        m = mutagen.File(path)
        br = getattr(getattr(m, "info", None), "bitrate", None)
        return int(br / 1000) if br else None
    except Exception:
        return None


def scan(cfg, analysis=None, rb=None, progress=None):
    rules = b.configure(cfg)
    ex = reglas.Excluder(rules)
    dest = Path(cfg["dest_root"])
    roots = [dest, Path(cfg["inbox"])] + [Path(r) for r in cfg.get("library_roots") or []]
    skip = tuple(str(r / d) + os.sep for r in roots for d in ("_duplicados", "_Informes", "_organizadas"))
    if progress:
        progress("Revisando todas tus carpetas…", 0.05)
    files = [f for f in b.scan(roots, None, ex) if not f.path.startswith(skip)]
    rb = rb or {}
    used = defaultdict(set)
    for pl in analysis or []:
        for r in pl.get("tracks") or []:
            if r.get("source"):
                used[r["source"]].add(pl["name"])

    def akey(f):
        return f.artist_n.split(" and ")[0].split(",")[0].strip()

    # 1) agrupar por canción (artista + título + versión); 2) confirmar por duración / contenido
    by_song = defaultdict(list)
    for f in files:
        if f.core and akey(f) not in b.UNKNOWN_ARTISTS:
            by_song[(akey(f), f.core, f.extras)].append(f)
    # copias exactas aunque el nombre sea distinto
    by_size = defaultdict(list)
    for f in files:
        try:
            by_size[os.path.getsize(f.path)].append(f)
        except OSError:
            pass
    cands = [g for g in by_song.values() if len(g) > 1]
    exact_cands = [g for g in by_size.values() if len(g) > 1]
    total = len(cands) + len(exact_cands)

    groups, seen_sets = [], set()

    def add_group(members, kind, seconds):
        key = frozenset(f.path for f in members)
        if key in seen_sets:
            return
        # un grupo exacto ya incluido en uno de «misma canción» no se repite
        for s in list(seen_sets):
            if key <= s:
                return
        seen_sets.add(key)
        groups.append((members, kind, seconds))

    for n, g in enumerate(exact_cands, 1):
        if progress and n % 50 == 0:
            progress(f"Buscando copias exactas {n}/{len(exact_cands)}…", 0.1 + 0.3 * n / max(1, len(exact_cands)))
        by_hash = defaultdict(list)
        for f in g:
            h = _quick_hash(f.path)
            if h:
                by_hash[h].append(f)
        for m in by_hash.values():
            if len(m) > 1:
                add_group(m, "identicos", b.duration(m[0].path))

    for n, g in enumerate(cands, 1):
        if progress and n % 25 == 0:
            progress(f"Comparando canciones {n}/{len(cands)}…", 0.4 + 0.5 * n / max(1, len(cands)))
        subs = []
        for f in sorted(g, key=lambda x: b.duration(x.path) or 0):
            d = b.duration(f.path)
            for s in subs:
                if b.same_length(s[0][1], d):
                    s.append((f, d))
                    break
            else:
                subs.append([(f, d)])
        for s in subs:
            if len(s) > 1:
                members = [f for f, _ in s]
                hashes = {_quick_hash(f.path) for f in members}
                add_group(members, "identicos" if len(hashes) == 1 else "cancion", s[0][1])
    b.save_durations()

    out = []
    for members, kind, seconds in groups:
        files_info = []
        for f in members:
            info = rb.get(f.path) or {}
            h = armonia.info(f.path)
            try:
                size = os.path.getsize(f.path)
            except OSError:
                size = 0
            files_info.append({
                "path": f.path, "size": size, "ext": Path(f.path).suffix.lower().lstrip("."),
                "bitrate": _bitrate(f.path), "seconds": b.duration(f.path),
                "key": h.get("key"), "energy": h.get("energy"), "mik": h.get("mik"),
                "rb_cues": info.get("cues", 0), "rb_playlists": info.get("playlists", 0), "in_rb": f.path in rb,
                "used_by": sorted(used.get(f.path, ())), "in_dest": f.path.startswith(str(dest) + os.sep),
            })

        def score(x):
            return (-x["rb_cues"], -x["rb_playlists"], -x["in_rb"], -bool(x["mik"]), -len(x["used_by"]),
                    reglas.quality(x["path"], rules), -(x["bitrate"] or 0), -x["in_dest"], -x["size"])
        files_info.sort(key=score)
        k = files_info[0]
        if k["rb_cues"]:
            why = "tiene cues en Rekordbox"
        elif k["rb_playlists"]:
            why = f"está en {k['rb_playlists']} playlist(s) de Rekordbox"
        elif k["in_rb"]:
            why = "está en tu colección de Rekordbox"
        elif k["mik"]:
            why = "está analizada con Mixed In Key"
        elif k["used_by"]:
            why = "la usan tus playlists"
        else:
            why = "mejor calidad"
        a = members[0]
        out.append({"id": f"g{len(out)}", "kind": kind, "song": f"{a.artist} - {a.title}" if a.artist else a.title,
                    "seconds": seconds, "files": files_info, "keep": k["path"], "why": why,
                    "bytes": sum(x["size"] for x in files_info[1:])})
    armonia.save()
    out.sort(key=lambda g: (g["kind"] != "identicos", g["song"].lower()))
    if progress:
        progress(f"{len(out)} grupos de duplicados.", 1)
    return {"groups": out, "files_scanned": len(files), "dest": str(dest),
            "bytes": sum(g["bytes"] for g in out), "rb_read": bool(rb)}


def to_unify_plan(scan_result, choices):
    """choices: {group_id: {"keep": ruta, "remove": [rutas]}} -> plan para unificar.apply."""
    dups = []
    by_id = {g["id"]: g for g in scan_result["groups"]}
    for gid, ch in (choices or {}).items():
        g = by_id.get(gid)
        if not g:
            continue
        paths = {f["path"] for f in g["files"]}
        keep = ch.get("keep") if ch.get("keep") in paths else g["keep"]
        remove = [p for p in ch.get("remove") or [] if p in paths and p != keep]
        if remove:
            dups.append({"id": gid, "song": g["song"], "keep": keep, "remove": remove,
                         "rb": any(f["in_rb"] for f in g["files"])})
    return {"dest": scan_result["dest"], "merges": [], "dups": dups, "empty": []}
