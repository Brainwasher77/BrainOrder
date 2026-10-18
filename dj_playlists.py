"""Leer (solo lectura) las playlists que creaste tú en cada programa de DJ.

Para cada programa activo devuelve {id_en_el_programa: {"name", "paths": [rutas en orden]}}, sin contar
la carpeta que crea BrainOrder (esas ya son de BrainOrder). Se usa para avisarte cuando creas una
playlist nueva en Rekordbox, Traktor, Serato o Engine DJ y para importarla como playlist de BrainOrder.
Nada de esto escribe en los programas.
"""
import os
import sqlite3
from pathlib import Path

import destinos
from config import log
from plataforma import native

LABELS = {"rekordbox": "Rekordbox", "traktor": "Traktor", "serato": "Serato", "engine": "Engine DJ"}


def _folder(cfg):
    return cfg.get("rekordbox_folder") or "BrainOrder"


# ---------------------------------------------------------------- Rekordbox
def rekordbox(cfg):
    import rekordbox_sync
    con = rekordbox_sync.connect_ro()
    try:
        alive = "COALESCE(rb_local_deleted, 0) = 0"
        rows = con.execute(f"SELECT ID, Name, ParentID, COALESCE(Attribute, 0) FROM djmdPlaylist WHERE {alive}").fetchall()
        by_id = {str(r[0]): r for r in rows}
        ours = {str(r[0]) for r in rows if r[2] == "root" and r[1] == _folder(cfg) and r[3] == 1}

        def inside_ours(pid):
            seen = 0
            while pid and pid != "root" and seen < 50:
                if pid in ours:
                    return True
                pid = str(by_id[pid][2]) if pid in by_id else None
                seen += 1
            return False
        lists = {str(r[0]): {"name": r[1], "paths": []} for r in rows
                 if r[3] == 0 and not inside_ours(str(r[2]))}  # 0 = playlist normal (1 carpeta, 4 inteligente)
        if lists:
            marks = ",".join("?" * len(lists))
            q = (f"SELECT sp.PlaylistID, c.FolderPath FROM djmdSongPlaylist sp JOIN djmdContent c ON c.ID = sp.ContentID "
                 f"WHERE sp.PlaylistID IN ({marks}) AND COALESCE(sp.rb_local_deleted, 0) = 0 "
                 f"ORDER BY sp.PlaylistID, COALESCE(sp.TrackNo, 0)")
            for pid, fp in con.execute(q, list(lists)):
                if fp:
                    lists[str(pid)]["paths"].append(native(fp))
        return lists
    finally:
        con.close()


def rekordbox_stamp(cfg):
    import rb_cambios
    return rb_cambios.db_mtime()


# ---------------------------------------------------------------- Traktor
def traktor(cfg):
    from destinos import traktor as T
    path = T.nml_path(cfg)
    if not path or not Path(path).exists():
        return {}
    col = T.Collection(path)
    out = {}
    skip = {"_RECORDINGS", "_LOOPS", "_HISTORY", "Preparation"}

    def walk(node, trail, ours):
        sub = node.find("SUBNODES")
        for n in (sub.findall("NODE") if sub is not None else []):
            name = n.get("NAME") or ""
            if n.get("TYPE") == "FOLDER":
                walk(n, trail + [name], ours or (not trail and name == _folder(cfg)))
            elif n.get("TYPE") == "PLAYLIST" and not ours and name not in skip:
                pl = n.find("PLAYLIST")
                if pl is None or pl.get("TYPE") not in (None, "LIST"):
                    continue
                paths = []
                for pk in pl.iter("PRIMARYKEY"):
                    e = col.by_key.get(pk.get("KEY"))
                    loc = e.find("LOCATION") if e is not None else None
                    if loc is not None:
                        paths.append(T._join(loc.get("VOLUME", ""), loc.get("DIR", ""), loc.get("FILE", ""), col.root_volume))
                ref = pl.get("UUID") or "/".join(trail + [name])
                out[ref] = {"name": name, "paths": paths}
    pls = col.root.find("PLAYLISTS")
    root = pls.find("NODE") if pls is not None else None
    if root is not None:
        walk(root, [], False)
    return out


def traktor_stamp(cfg):
    from destinos import traktor as T
    p = T.nml_path(cfg)
    try:
        return os.stat(p).st_mtime if p else None
    except OSError:
        return None


# ---------------------------------------------------------------- Serato
def serato(cfg):
    from destinos import serato as S
    sdir = S.home_serato(cfg)
    sub = sdir / "Subcrates"
    if not sub.is_dir():
        return {}
    prefix = S._crate_name(_folder(cfg))
    root = S._volume_of(str(sdir))[0]
    out = {}
    for f in sorted(sub.glob("*.crate")):
        stem = f.stem
        if stem == prefix or stem.startswith(prefix + "%%"):
            continue
        try:
            rels = S.crate_tracks(f.read_bytes())
        except OSError:
            continue
        out[stem] = {"name": stem.split("%%")[-1], "paths": [os.path.join(root, r) for r in rels]}
    return out


def serato_stamp(cfg):
    from destinos import serato as S
    sub = S.home_serato(cfg) / "Subcrates"
    try:
        return max([sub.stat().st_mtime] + [f.stat().st_mtime for f in sub.glob("*.crate")])
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- Engine DJ
def engine(cfg):
    from destinos import engine as E
    if not E.available(cfg):
        return {}
    src = sqlite3.connect(f"file:{E.db_path(cfg)}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:")
    try:
        src.backup(db)
    finally:
        src.close()
    try:
        lib_dir = str(E.library_dir(cfg))
        rows = db.execute("SELECT id, title, parentListId FROM Playlist").fetchall()
        ours = {r[0] for r in rows if r[2] == 0 and r[1] == _folder(cfg)}
        has_child = {r[2] for r in rows}
        paths_of = dict(db.execute("SELECT id, path FROM Track").fetchall())

        class L:  # para reutilizar el recorrido de la lista enlazada
            pass
        lib = L()
        lib.db = db
        out = {}
        for lid, title, parent in rows:
            if lid in ours or parent in ours or lid in has_child:
                continue
            tids = E.Library.entries(lib, lid)
            out[str(lid)] = {"name": title, "paths": [os.path.normpath(os.path.join(lib_dir, paths_of[t]))
                                                      for t in tids if paths_of.get(t)]}
        return out
    finally:
        db.close()


def engine_stamp(cfg):
    from destinos import engine as E
    try:
        p = E.db_path(cfg)
        w = p.with_name("m.db-wal")
        return max(p.stat().st_mtime, w.stat().st_mtime if w.exists() else 0)
    except OSError:
        return None


READERS = {"rekordbox": (rekordbox, rekordbox_stamp), "traktor": (traktor, traktor_stamp),
           "serato": (serato, serato_stamp), "engine": (engine, engine_stamp)}


def enabled_programs(cfg):
    return [k for k in READERS if k in destinos.DESTINATIONS and destinos.DESTINATIONS[k].enabled(cfg)]


def read(cfg, program):
    try:
        return READERS[program][0](cfg)
    except Exception as e:
        log(f"No pude leer las playlists de {LABELS.get(program, program)}: {e!r}")
        return None


def stamp(cfg, program):
    try:
        return READERS[program][1](cfg)
    except Exception:
        return None
