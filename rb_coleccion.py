"""Operaciones sobre la COLECCIÓN de Rekordbox (master.db) que no pierden nada y se pueden deshacer.

- set_path:   la pista apunta a otro archivo (mismo ID: conserva cues, playlists, historial y análisis).
- merge:      dos entradas son la misma canción: todo lo de «lost» pasa a «keep» (playlists en la misma
              posición, cues si «keep» no tiene, historial, etiquetas…) y «lost» sale de la colección.
- delete:     saca una pista de la colección con todo lo que cuelga de ella (como lo hace Rekordbox: no
              deja filas huérfanas).
Cada operación anota en `undo` lo necesario para revertirla (filas completas de lo borrado y valores
anteriores de lo cambiado). Nada de esto hace commit: lo hace quien llama, una sola vez al final, así un
error a mitad de camino no deja la librería a medias.
Ojo: pyrekordbox.remove_from_playlist hace commit por su cuenta; aquí se usa _drop_song (sin commit).
"""
import base64
import os
from datetime import date, datetime

from config import log
from plataforma import native, rb_path

try:  # pyrekordbox 0.5+
    from pyrekordbox.masterdb import models as M
except ImportError:  # pragma: no cover - pyrekordbox 0.4
    from pyrekordbox.db6 import tables as M


def _child_models():
    """Tablas cuyas filas cuelgan de una pista (columna ContentID)."""
    out = []
    for name in dir(M):
        cls = getattr(M, name)
        t = getattr(cls, "__table__", None)
        if t is not None and "ContentID" in t.c and getattr(cls, "__tablename__", "") != "djmdContent":
            out.append(cls)
    return out


CHILDREN = _child_models()
_BY_TABLE = {c.__tablename__: c for c in CHILDREN}
_BY_TABLE["djmdContent"] = M.DjmdContent


# ---------------------------------------------------------------- filas <-> JSON (para deshacer)
def _enc(v):
    if isinstance(v, datetime):
        return {"__dt": v.isoformat()}
    if isinstance(v, date):
        return {"__d": v.isoformat()}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"__b": base64.b64encode(bytes(v)).decode()}
    return v


def _dec(v):
    if isinstance(v, dict):
        if "__dt" in v:
            return datetime.fromisoformat(v["__dt"])
        if "__d" in v:
            return date.fromisoformat(v["__d"])
        if "__b" in v:
            return base64.b64decode(v["__b"])
    return v


_DB = [None]  # base abierta de la operación en curso (para leer filas tal cual están guardadas)


def snapshot(obj):
    """La fila TAL CUAL está guardada (sin pasar por los tipos de pyrekordbox, que reescriben las fechas)."""
    from sqlalchemy import text
    t = obj.__table__
    pk = [c.key for c in t.primary_key.columns]
    db = _DB[0]
    if db is not None:
        q = text(f'SELECT * FROM "{t.name}" WHERE ' + " AND ".join(f'"{k}" = :{k}' for k in pk))
        row = db.session.execute(q, {k: getattr(obj, k) for k in pk}).mappings().first()
        if row is not None:
            return {"table": t.name, "raw": True, "cols": {k: _enc(v) for k, v in dict(row).items()}}
    return {"table": t.name, "cols": {c.key: _enc(getattr(obj, c.key)) for c in t.columns}}


def _restore(db, snap):
    from sqlalchemy import text
    cls = _BY_TABLE[snap["table"]]
    pk = [c.key for c in cls.__table__.primary_key.columns]
    cols = {k: _dec(v) for k, v in snap["cols"].items()}
    if db.query(cls).filter_by(**{k: cols[k] for k in pk}).first() is not None:
        return False  # ya existe (se recreó después): no se pisa
    if snap.get("raw"):
        names = list(cols)
        db.session.execute(text(f'INSERT INTO "{snap["table"]}" (' + ", ".join(f'"{k}"' for k in names) + ") VALUES ("
                                + ", ".join(f":{k}" for k in names) + ")"), cols)
    else:
        db.session.add(cls(**cols))
    return True


# ---------------------------------------------------------------- utilidades
def content_path(c):
    return native(c.FolderPath) if c is not None and c.FolderPath else None


def _drop_song(db, s):
    """Quita una canción de una playlist y corre las siguientes una posición (sin commit)."""
    pid, no = s.PlaylistID, s.TrackNo or 0
    db.session.delete(s)
    db.registry.on_delete(s)
    db.session.flush()
    for o in db.query(M.DjmdSongPlaylist).filter(M.DjmdSongPlaylist.PlaylistID == pid,
                                                 M.DjmdSongPlaylist.TrackNo > no):
        o.TrackNo = (o.TrackNo or 0) - 1


def _insert_song(db, snap):
    """Vuelve a poner una canción en su playlist, en su posición y con su misma fila (ID/UUID)."""
    cols = {k: _dec(v) for k, v in snap["cols"].items()}
    pid, cid = str(cols.get("PlaylistID")), str(cols.get("ContentID"))
    if db.get_playlist(ID=pid) is None or db.get_content(ID=cid) is None:
        return False
    if db.query(M.DjmdSongPlaylist).filter_by(ID=cols["ID"]).first() is not None:
        return False
    n = db.get_playlist_songs(PlaylistID=pid).count()
    no = cols.get("TrackNo") or n + 1
    if no > n + 1:
        no = n + 1
    for o in db.query(M.DjmdSongPlaylist).filter(M.DjmdSongPlaylist.PlaylistID == pid,
                                                 M.DjmdSongPlaylist.TrackNo >= no):
        o.TrackNo = (o.TrackNo or 0) + 1
    db.session.flush()
    cols["TrackNo"] = no
    _restore(db, {**snap, "cols": {k: _enc(v) for k, v in cols.items()}})
    db.session.flush()
    return True


# ---------------------------------------------------------------- operaciones
def set_path(db, c, new, undo, anlz):
    """La pista c pasa a apuntar a `new`. Los archivos de análisis (ANLZ) se corrigen DESPUÉS del commit
    (write_anlz) para que un error no deje la base y los ANLZ desparejos."""
    new = rb_path(new)
    undo.append({"op": "path", "id": str(c.ID), "FolderPath": c.FolderPath, "OrgFolderPath": c.OrgFolderPath,
                 "FileNameL": c.FileNameL, "FileSize": c.FileSize})
    try:
        files = db.read_anlz_files(c.ID)
    except Exception:
        files = {}
    old = c.FolderPath
    c.FolderPath = new
    if c.OrgFolderPath and rb_path(c.OrgFolderPath) == rb_path(old or ""):
        c.OrgFolderPath = new
    name = new.rsplit("/", 1)[-1]
    if c.FileNameL != name:
        c.FileNameL = name
    try:
        c.FileSize = os.path.getsize(native(new))
    except OSError:
        pass
    anlz.append((files, new))


def write_anlz(anlz):
    for files, new in anlz:
        for apath, a in (files or {}).items():
            try:
                p = new
                if str(a.get("path") or "").startswith("?/"):
                    p = "?/" + new.rsplit("/", 1)[-1]
                a.set_path(p)
                a.save(apath)
            except Exception as e:
                log(f"ANLZ {apath}: {e}")


def delete(db, c, undo):
    """Saca la pista de la colección con todo lo que cuelga de ella (las playlists se reordenan)."""
    _DB[0] = db
    rows = []
    for s in list(db.query(M.DjmdSongPlaylist).filter(M.DjmdSongPlaylist.ContentID == c.ID)):
        rows.append({"song": snapshot(s)})
        _drop_song(db, s)
    for cls in CHILDREN:
        if cls is M.DjmdSongPlaylist:
            continue
        for r in list(db.query(cls).filter(cls.ContentID == c.ID)):
            rows.append({"row": snapshot(r)})
            db.session.delete(r)
            db.registry.on_delete(r)
    rows.append({"row": snapshot(c)})
    db.session.delete(c)
    db.registry.on_delete(c)
    db.session.flush()
    undo.append({"op": "delete", "id": str(c.ID), "rows": rows})


def merge(db, lost, keep, undo):
    """lost y keep son la misma canción: lost se va de la colección y keep queda en su lugar en cada
    playlist (misma posición). Si keep no tiene cues, se queda con los de lost. Lo demás que cuelga de lost
    (historial, etiquetas…) pasa a keep si keep no lo tiene ya."""
    if lost is None or keep is None or str(lost.ID) == str(keep.ID):
        return
    moved = []
    for s in list(db.query(M.DjmdSongPlaylist).filter(M.DjmdSongPlaylist.ContentID == lost.ID)):
        if db.get_playlist_songs(PlaylistID=s.PlaylistID, ContentID=keep.ID).first() is None:
            moved.append({"table": "djmdSongPlaylist", "pk": s.ID, "ContentID": str(lost.ID)})
            s.ContentID = keep.ID
    keep_has_cues = db.query(M.DjmdCue).filter(M.DjmdCue.ContentID == keep.ID).first() is not None
    if not keep_has_cues:
        for q in list(db.query(M.DjmdCue).filter(M.DjmdCue.ContentID == lost.ID)):
            moved.append({"table": "djmdCue", "pk": q.ID, "ContentID": str(lost.ID), "ContentUUID": q.ContentUUID})
            q.ContentID, q.ContentUUID = keep.ID, keep.UUID
        cc = getattr(M, "ContentCue", None)
        if cc is not None and db.query(cc).filter(cc.ContentID == keep.ID).first() is None:
            for q in list(db.query(cc).filter(cc.ContentID == lost.ID)):
                moved.append({"table": "contentCue", "pk": q.ID, "ContentID": str(lost.ID)})
                q.ContentID = keep.ID
    for name in ("DjmdSongHistory", "DjmdSongMyTag", "DjmdSongTagList", "DjmdSongHotCueBanklist", "DjmdSongSampler"):
        cls = getattr(M, name, None)
        if cls is None:
            continue
        for r in list(db.query(cls).filter(cls.ContentID == lost.ID)):
            moved.append({"table": cls.__tablename__, "pk": r.ID, "ContentID": str(lost.ID)})
            r.ContentID = keep.ID
    db.session.flush()
    undo.append({"op": "moved", "rows": moved})
    delete(db, lost, undo)  # lo que queda (cues repetidos, mezclador, archivos de análisis…) se va con ella


def revert(db, undo, progress=None):
    """Deshace lo anotado (en orden inverso). -> (hechas, saltadas)"""
    _DB[0] = db
    done = skipped = 0
    for n, u in enumerate(reversed(undo or []), 1):
        if progress and n % 50 == 0:
            progress(f"Deshaciendo {n}/{len(undo)}…", n / max(1, len(undo)))
        try:
            if u["op"] == "path":
                c = db.get_content(ID=u["id"])
                if c is None:
                    skipped += 1
                    continue
                c.FolderPath, c.OrgFolderPath, c.FileNameL = u["FolderPath"], u["OrgFolderPath"], u["FileNameL"]
                if u.get("FileSize") is not None:
                    c.FileSize = u["FileSize"]
                done += 1
            elif u["op"] == "delete":
                rows = u["rows"]
                content = [r for r in rows if "row" in r and r["row"]["table"] == "djmdContent"]
                for r in content:  # primero la pista, después lo que cuelga de ella
                    _restore(db, r["row"])
                db.session.flush()
                for r in rows:
                    if "row" in r and r["row"]["table"] != "djmdContent":
                        _restore(db, r["row"])
                db.session.flush()
                for r in sorted((r for r in rows if "song" in r), key=lambda r: r["song"]["cols"].get("TrackNo") or 0):
                    _insert_song(db, r["song"])
                done += 1
            elif u["op"] == "moved":
                for m in u["rows"]:
                    cls = _BY_TABLE.get(m["table"])
                    r = db.query(cls).filter_by(ID=m["pk"]).first() if cls is not None else None
                    if r is None:
                        continue
                    r.ContentID = m["ContentID"]
                    if "ContentUUID" in m:
                        r.ContentUUID = m["ContentUUID"]
                done += 1
            db.session.flush()
        except Exception as e:
            log(f"deshacer en Rekordbox ({u.get('op')}): {e!r}")
            skipped += 1
    return done, skipped
