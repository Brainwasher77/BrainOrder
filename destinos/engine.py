"""Engine DJ (Denon / Numark / Rane) como destino: playlists dentro de su librería.

La librería está en «Engine Library/Database2/m.db» (SQLite). Rutas de pistas relativas a la carpeta
Engine Library («../DJ Library/x.mp3»). Las playlists y sus pistas son listas enlazadas
(nextListId / nextEntityId) que la propia base mantiene con triggers.

Reglas de Engine para herramientas externas que respetamos:
- Engine DJ tiene que estar cerrado.
- No se toca el esquema: solo se insertan/actualizan filas con las columnas que ya existen.
- Antes de cambiar nada se respalda m.db (fuera de Database2).
"""
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from config import log

KEY = "engine"
LABEL = "Engine DJ"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

NEED = {"Track": {"id", "path", "filename"},
        "Playlist": {"id", "title", "parentListId", "nextListId"},
        "PlaylistEntity": {"id", "listId", "trackId", "databaseUuid", "nextEntityId"},
        "Information": {"uuid"}}


class EngineError(Exception):
    pass


def library_dir(cfg):
    s = ((cfg.get("destinations") or {}).get(KEY) or {}).get("dir")
    return Path(s) if s else Path.home() / "Music" / "Engine Library"


def db_path(cfg):
    return library_dir(cfg) / "Database2" / "m.db"


def available(cfg):
    return db_path(cfg).exists()


def enabled(cfg):
    return bool(((cfg.get("destinations") or {}).get(KEY) or {}).get("enabled")) and available(cfg)


def running():
    try:
        import plataforma
        if IS_MAC:
            return bool(plataforma.any_process(lambda l: "Engine DJ" in l or "Engine Prime" in l))
        if IS_WIN:
            return bool(plataforma.any_process(lambda l: "engine dj" in l.lower() or "enginedj" in l.lower()))
    except Exception:
        return False
    return False


def backup(cfg):
    src = db_path(cfg)
    bdir = library_dir(cfg) / "BrainOrder respaldos"
    bdir.mkdir(parents=True, exist_ok=True)
    dst = bdir / f"m.{datetime.now():%Y%m%d-%H%M%S}.db"
    # copia consistente aunque haya WAL
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    for old in sorted(bdir.glob("m.*.db"))[:-5]:
        try:
            old.unlink()
        except OSError:
            pass
    return dst.name


class Library:
    def __init__(self, cfg):
        self.dir = library_dir(cfg)
        self.db = sqlite3.connect(db_path(cfg), timeout=10)
        self.cols = {}
        for t in NEED:
            self.cols[t] = {r[1] for r in self.db.execute(f"PRAGMA table_info({t})")}
            miss = NEED[t] - self.cols[t]
            if miss:
                raise EngineError(f"Esta versión de Engine DJ no es compatible todavía (falta {t}.{', '.join(miss)}).")
        row = self.db.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
        if not row or not row[0]:
            raise EngineError("La librería de Engine DJ no tiene identificador (Information.uuid).")
        self.uuid = row[0]
        self.now = int(time.time())

    # -- pistas
    def rel(self, path):
        try:
            return os.path.relpath(path, self.dir).replace(os.sep, "/")
        except ValueError:  # otro disco en Windows
            return None

    def track_id(self, rel):
        r = self.db.execute("SELECT id FROM Track WHERE path = ?", (rel,)).fetchone()
        return r[0] if r else None

    def add_track(self, path, rel, title, artist, album, seconds):
        p = Path(path)
        try:
            size = p.stat().st_size
        except OSError:
            size = None
        vals = {"path": rel, "filename": p.name, "title": title or p.stem, "artist": artist or None,
                "album": album or None, "length": int(seconds) if seconds else None, "fileBytes": size,
                "fileType": p.suffix.lower().lstrip("."), "isAnalyzed": 0, "isAvailable": 1,
                "isMetadataImported": 0, "isPlayed": 0, "dateAdded": self.now, "dateCreated": self.now,
                "lastEditTime": self.now, "isBeatGridLocked": 0, "playOrder": None}
        vals = {k: v for k, v in vals.items() if k in self.cols["Track"]}
        q = f"INSERT INTO Track ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})"
        return self.db.execute(q, list(vals.values())).lastrowid

    # -- playlists
    def playlist(self, title, parent_id):
        r = self.db.execute("SELECT id FROM Playlist WHERE title = ? AND parentListId = ?",
                            (title, parent_id)).fetchone()
        if r:
            return r[0]
        vals = {"title": title, "parentListId": parent_id, "isPersisted": 1, "nextListId": 0,
                "lastEditTime": self.now, "isExplicitlyExported": 1}
        vals = {k: v for k, v in vals.items() if k in self.cols["Playlist"]}
        q = f"INSERT INTO Playlist ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})"
        return self.db.execute(q, list(vals.values())).lastrowid  # el trigger la encadena al final

    def entries(self, list_id):
        """Pistas de la playlist en orden (siguiendo nextEntityId)."""
        rows = self.db.execute("SELECT id, trackId, nextEntityId FROM PlaylistEntity WHERE listId = ?",
                               (list_id,)).fetchall()
        by_id = {r[0]: r for r in rows}
        pointed = {r[2] for r in rows}
        heads = [r for r in rows if r[0] not in pointed]
        out, cur, guard = [], heads[0] if heads else None, 0
        while cur and guard <= len(rows):
            out.append(cur[1])
            cur = by_id.get(cur[2])
            guard += 1
        return out

    def set_entries(self, list_id, track_ids):
        if self.entries(list_id) == track_ids:
            return False
        self.db.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (list_id,))
        has_mr = "membershipReference" in self.cols["PlaylistEntity"]
        for tid in track_ids:
            if has_mr:
                new = self.db.execute("INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, "
                                      "membershipReference) VALUES (?, ?, ?, 0, 0)",
                                      (list_id, tid, self.uuid)).lastrowid
            else:
                new = self.db.execute("INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId) "
                                      "VALUES (?, ?, ?, 0)", (list_id, tid, self.uuid)).lastrowid
            # la que era la última ahora apunta a la nueva
            self.db.execute("UPDATE PlaylistEntity SET nextEntityId = ? WHERE listId = ? AND nextEntityId = 0 "
                            "AND id <> ?", (new, list_id, new))
        if "lastEditTime" in self.cols["Playlist"]:
            self.db.execute("UPDATE Playlist SET lastEditTime = ? WHERE id = ?", (self.now, list_id))
        return True


def _open(cfg):
    if not available(cfg):
        raise EngineError(f"No encontré la librería de Engine DJ ({db_path(cfg)}). Ábrelo una vez o elige la carpeta en Conexiones.")
    if running():
        raise EngineError("Engine DJ está abierto. Ciérralo y vuelve a intentarlo.")


def sync(analysis, cfg, progress=None):
    _open(cfg)
    bk = backup(cfg)
    lib = Library(cfg)
    stats = {"playlists_updated": 0, "tracks_added": 0, "backup": bk, "skipped": 0}
    try:
        with lib.db:
            folder = lib.playlist(cfg.get("rekordbox_folder") or "BrainOrder", 0)
            analysis = [p for p in analysis if not p.get("pending")]
            for i, pl in enumerate(analysis, 1):
                if progress:
                    progress(f"Engine DJ {i}/{len(analysis)}: {pl['name']}", i / max(1, len(analysis)))
                ids, seen = [], set()
                for r in pl["tracks"]:
                    if r["status"] not in ("ok", "elsewhere") or not r.get("source") or r["source"] in seen:
                        continue
                    seen.add(r["source"])
                    rel = lib.rel(r["source"])
                    if rel is None:
                        stats["skipped"] += 1
                        continue
                    tid = lib.track_id(rel)
                    if tid is None:
                        tid = lib.add_track(r["source"], rel, r["name"], ", ".join(r.get("artists") or []),
                                            r.get("album"), None)
                        stats["tracks_added"] += 1
                    if tid not in ids:
                        ids.append(tid)
                if lib.set_entries(lib.playlist(pl["name"], folder), ids):
                    stats["playlists_updated"] += 1
    except sqlite3.Error as e:
        raise EngineError(f"Error escribiendo en Engine DJ (no se guardó nada): {e}")
    finally:
        lib.db.close()
    log(f"Engine DJ: {stats}")
    return stats


def fix_paths(cfg, moved, repoint=None):
    if not available(cfg) or not (moved or repoint):
        return None
    _open(cfg)
    bk = backup(cfg)
    lib = Library(cfg)
    n = 0
    try:
        with lib.db:
            for old, keep in (repoint or {}).items():
                ro, rk = lib.rel(old), lib.rel(keep)
                t_old = lib.track_id(ro) if ro else None
                if t_old is None or rk is None:
                    continue
                t_keep = lib.track_id(rk)
                if t_keep is None:
                    continue
                # las playlists que usaban la copia repetida pasan a usar la que se conserva
                for (eid, lid) in lib.db.execute("SELECT id, listId FROM PlaylistEntity WHERE trackId = ?",
                                                  (t_old,)).fetchall():
                    dup = lib.db.execute("SELECT 1 FROM PlaylistEntity WHERE listId = ? AND trackId = ?",
                                         (lid, t_keep)).fetchone()
                    if dup:
                        lib.db.execute("DELETE FROM PlaylistEntity WHERE id = ?", (eid,))
                    else:
                        lib.db.execute("UPDATE PlaylistEntity SET trackId = ? WHERE id = ?", (t_keep, eid))
                    n += 1
            for old, new in (moved or {}).items():
                ro, rn = lib.rel(old), lib.rel(new)
                if not ro or not rn or lib.track_id(rn) is not None:
                    continue
                c = lib.db.execute("UPDATE Track SET path = ?, filename = ? WHERE path = ?",
                                   (rn, Path(new).name, ro)).rowcount
                n += c
    except sqlite3.Error as e:
        raise EngineError(f"Error corrigiendo rutas en Engine DJ (no se guardó nada): {e}")
    finally:
        lib.db.close()
    return {"refs": n, "backup": bk}


def edit(cfg, renames=None, deletes=None):
    """Renombra / elimina playlists dentro de la carpeta de BrainOrder en Engine DJ (respaldo antes)."""
    renames, deletes = dict(renames or {}), list(deletes or [])
    if not (renames or deletes) or not available(cfg):
        return None
    folder = cfg.get("rekordbox_folder") or "BrainOrder"
    with sqlite3.connect(f"file:{db_path(cfg)}?mode=ro", uri=True) as ro:
        f = ro.execute("SELECT id FROM Playlist WHERE title = ? AND parentListId = 0", (folder,)).fetchone()
        names = {r[0] for r in ro.execute("SELECT title FROM Playlist WHERE parentListId = ?", (f[0],))} if f else set()
    if not any(o in names for o in renames) and not any(n in names for n in deletes):
        return {"renamed": 0, "deleted": 0}
    _open(cfg)
    bk = backup(cfg)
    lib = Library(cfg)
    out = {"renamed": 0, "deleted": 0, "backup": bk}
    try:
        with lib.db:
            fid = lib.db.execute("SELECT id FROM Playlist WHERE title = ? AND parentListId = 0", (folder,)).fetchone()[0]
            lid = lambda t: (lib.db.execute("SELECT id FROM Playlist WHERE title = ? AND parentListId = ?", (t, fid)).fetchone() or [None])[0]

            def drop(i):
                lib.db.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (i,))
                lib.db.execute("DELETE FROM Playlist WHERE id = ?", (i,))  # el trigger re-encadena la lista
            for old, new in renames.items():
                i = lid(old)
                if i is None:
                    continue
                if lid(new) is not None:
                    drop(i)
                    out["deleted"] += 1
                else:
                    lib.db.execute("UPDATE Playlist SET title = ? WHERE id = ?", (new, i))
                    out["renamed"] += 1
            for name in deletes:
                i = lid(name)
                if i is not None:
                    drop(i)
                    out["deleted"] += 1
    finally:
        lib.db.close()
    return out
