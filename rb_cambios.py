"""Cambios hechos A MANO en Rekordbox dentro de la carpeta de BrainOrder.

Cada vez que BrainOrder escribe sus playlists en Rekordbox guarda una «foto» (baseline):
    {id de la playlist en Rekordbox: {pid, name, paths: [rutas en orden]}}
Después compara esa foto con lo que hay ahora en Rekordbox y detecta:
    created  – creaste una playlist nueva dentro de la carpeta
    deleted  – borraste una playlist que BrainOrder había creado
    renamed  – le cambiaste el nombre
    added    – le agregaste canciones
    removed  – le quitaste canciones
Leer no necesita que Rekordbox esté cerrado: se lee una copia de master.db.
"""
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from config import SUPPORT_DIR, log
from plataforma import native

BASELINE = SUPPORT_DIR / "rb_baseline.json"
_LOCK = threading.Lock()


def load_baseline():
    try:
        return json.loads(BASELINE.read_text("utf-8"))
    except Exception:
        return {}


def save_baseline(data):
    with _LOCK:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BASELINE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        os.replace(tmp, BASELINE)


def merge_baseline(new):
    """Agrega/actualiza la foto de las playlists que BrainOrder acaba de escribir."""
    if not new:
        return
    data = load_baseline()
    data.update(new)
    save_baseline(data)


def db_mtime():
    import rekordbox_sync
    p = rekordbox_sync.RB_DIR / "master.db"
    try:
        st = p.stat()
        w = p.with_name("master.db-wal")
        return max(st.st_mtime, w.stat().st_mtime if w.exists() else 0)
    except OSError:
        return None


def _read_direct(cfg, src):
    """Lectura directa de solo lectura (rápida: no copia la librería)."""
    import rekordbox_sync
    con = rekordbox_sync.connect_ro(src)
    try:
        alive = "COALESCE(rb_local_deleted, 0) = 0"
        folder = cfg.get("rekordbox_folder") or "BrainOrder"
        row = con.execute(f"SELECT ID FROM djmdPlaylist WHERE ParentID = 'root' AND Name = ? AND Attribute = 1 AND {alive} "
                          "ORDER BY Seq LIMIT 1", (folder,)).fetchone()
        if row is None:
            return {}
        pls = con.execute(f"SELECT ID, Name FROM djmdPlaylist WHERE ParentID = ? AND COALESCE(Attribute, 0) = 0 AND {alive}",
                          (row[0],)).fetchall()
        out = {str(pid): {"name": name, "paths": []} for pid, name in pls}
        if out:
            marks = ",".join("?" * len(out))
            q = (f"SELECT sp.PlaylistID, c.FolderPath FROM djmdSongPlaylist sp JOIN djmdContent c ON c.ID = sp.ContentID "
                 f"WHERE sp.PlaylistID IN ({marks}) AND COALESCE(sp.rb_local_deleted, 0) = 0 "
                 f"ORDER BY sp.PlaylistID, COALESCE(sp.TrackNo, 0)")
            for pid, fp in con.execute(q, list(out)):
                if fp:
                    out[str(pid)]["paths"].append(native(fp))
        return out
    finally:
        con.close()


def read_state(cfg, path=None):
    """Playlists dentro de la carpeta de BrainOrder en Rekordbox -> {id: {name, paths}} (None si no hay librería)."""
    import rekordbox_sync
    src = Path(path) if path else rekordbox_sync.RB_DIR / "master.db"
    if not src.exists():
        return None
    try:
        return _read_direct(cfg, src)
    except Exception as e:
        log(f"Rekordbox: lectura directa falló ({e!r}); uso una copia")
    return _read_copy(cfg, path)


def _read_copy(cfg, path=None):
    import rekordbox_sync
    try:
        from pyrekordbox import MasterDatabase as DB
    except ImportError:  # pragma: no cover
        from pyrekordbox import Rekordbox6Database as DB
    src = Path(path) if path else rekordbox_sync.RB_DIR / "master.db"
    if not src.exists():
        return None
    tmpdir = tempfile.mkdtemp(prefix="brainorder-rb-")
    try:
        for suffix in ("", "-wal", "-shm"):
            f = src.with_name(src.name + suffix)
            if f.exists():
                shutil.copy2(f, Path(tmpdir) / ("master.db" + suffix))
        db = DB(path=Path(tmpdir) / "master.db")
        try:
            folder = cfg.get("rekordbox_folder") or "BrainOrder"
            root = next((p for p in db.get_playlist(ParentID="root", Name=folder) if (p.Attribute or 0) == 1), None)
            if root is None:
                return {}
            out = {}
            for p in db.get_playlist(ParentID=root.ID):
                if (p.Attribute or 0) != 0:
                    continue  # subcarpetas / listas inteligentes: no se tocan
                songs = sorted(p.Songs, key=lambda s: s.TrackNo or 0)
                out[str(p.ID)] = {"name": p.Name,
                                  "paths": [native(s.Content.FolderPath) for s in songs if s.Content and s.Content.FolderPath]}
            return out
        finally:
            try:
                db.close()
            except Exception:
                pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def diff(baseline, state, analysis=None):
    """Lista de cambios entre la foto y Rekordbox. Cada cambio tiene un id estable."""
    if state is None:
        return []
    by_name = {}
    for pl in analysis or []:
        by_name.setdefault(pl["name"], pl)
    changes = []
    for rid, cur in state.items():
        base = baseline.get(rid)
        if base is None:
            known = by_name.get(cur["name"])
            changes.append({"id": f"created:{rid}", "type": "created", "rb_id": rid, "name": cur["name"],
                            "paths": cur["paths"], "pid": known["id"] if known else None})
            continue
        pid = base.get("pid")
        if cur["name"] != base.get("name"):
            changes.append({"id": f"renamed:{rid}", "type": "renamed", "rb_id": rid, "pid": pid,
                            "name": cur["name"], "old_name": base.get("name")})
        old, new = base.get("paths") or [], cur["paths"]
        so, sn = set(old), set(new)
        added = [p for p in new if p not in so]
        removed = [p for p in old if p not in sn]
        if added:
            changes.append({"id": f"added:{rid}", "type": "added", "rb_id": rid, "pid": pid, "name": cur["name"],
                            "paths": added})
        if removed:
            changes.append({"id": f"removed:{rid}", "type": "removed", "rb_id": rid, "pid": pid, "name": cur["name"],
                            "paths": removed})
    for rid, base in baseline.items():
        if rid not in state:
            changes.append({"id": f"deleted:{rid}", "type": "deleted", "rb_id": rid, "pid": base.get("pid"),
                            "name": base.get("name"), "paths": base.get("paths") or []})
    return changes


def accept(state, rb_ids, pid_for=None):
    """Toma como nueva foto el estado actual de esas playlists (después de decidir qué hacer con sus cambios)."""
    data = load_baseline()
    for rid in rb_ids:
        if state and rid in state:
            data[rid] = {"pid": (pid_for or {}).get(rid) or (data.get(rid) or {}).get("pid"),
                         "name": state[rid]["name"], "paths": state[rid]["paths"]}
        else:
            data.pop(rid, None)
    save_baseline(data)
    log(f"Rekordbox: foto actualizada para {len(rb_ids)} playlist(s)")
