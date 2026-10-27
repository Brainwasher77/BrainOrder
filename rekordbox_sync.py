"""Replica las playlists de Spotify dentro de Rekordbox (carpeta 'Spotify' por defecto).

- Escribe directamente en master.db con pyrekordbox.
- Exige que Rekordbox esté cerrado.
- Hace copia de seguridad de master.db antes de cualquier cambio.
- Cada playlist queda con las canciones en el mismo orden que en Spotify
  (las que ya tienes, estén donde estén; un solo archivo aunque esté en varias playlists).
"""
import os
import shutil
from datetime import datetime
from pathlib import Path

from config import log

import plataforma
from plataforma import rb_path

RB_DIR = plataforma.rekordbox_dir()


class RekordboxError(Exception):
    pass


def rekordbox_running():
    """¿Rekordbox abierto? Usa la lista de procesos compartida (se consulta como mucho cada 2,5 s)."""
    def is_rb(line):
        return line.replace("\\", "/").rsplit("/", 1)[-1].lower() in ("rekordbox", "rekordbox.exe")
    hit = plataforma.any_process(is_rb)
    if hit is not None:
        return hit
    try:
        from pyrekordbox.utils import get_rekordbox_pid
        return bool(get_rekordbox_pid())
    except Exception:
        return False


def db_key():
    """Clave con la que Rekordbox cifra master.db (la misma que usa pyrekordbox)."""
    from pyrekordbox.utils import deobfuscate
    try:
        from pyrekordbox.masterdb.database import BLOB
    except ImportError:  # pyrekordbox 0.4
        from pyrekordbox.db6.database import BLOB
    return deobfuscate(BLOB)


def connect_ro(path=None):
    """Conexión de SOLO LECTURA a master.db, sin copiarlo (antes se copiaban ~200 MB en cada revisión).
    Rekordbox usa WAL: leer mientras está abierto es seguro y no lo bloquea."""
    from sqlcipher3 import dbapi2 as sq
    p = Path(path) if path else RB_DIR / "master.db"
    con = sq.connect(p.resolve().as_uri() + "?mode=ro", uri=True, timeout=5, check_same_thread=False)
    try:
        con.execute(f"PRAGMA key='{db_key()}'")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception:
        con.close()
        raise
    return con


def backup():
    """Respaldo de master.db en UN archivo consistente. Si hay cambios aún en el diario (-wal) se usa la
    copia en línea de SQLite (incluye todo); si no, una copia normal del archivo (más rápida)."""
    src = RB_DIR / "master.db"
    if not src.exists():
        raise RekordboxError(f"No encontré la librería de Rekordbox en {src}")
    dst = RB_DIR / f"master.backup.brainorder-{datetime.now():%Y%m%d-%H%M%S}.db"
    wal = src.with_name("master.db-wal")
    try:
        need = src.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
        if shutil.disk_usage(RB_DIR).free < need * 1.2 + 50 * 1024 * 1024:
            raise RekordboxError("No hay espacio en el disco para respaldar la librería de Rekordbox "
                                 f"(necesito unos {need // (1024 * 1024)} MB libres). Libera espacio y vuelve a intentar.")
    except OSError:
        pass
    done = False
    if wal.exists() and wal.stat().st_size > 0:
        tmp = dst.with_name("." + dst.name + ".tmp")
        try:
            from sqlcipher3 import dbapi2 as sq
            s = connect_ro(src)
            d = sq.connect(str(tmp))
            try:
                d.execute(f"PRAGMA key='{db_key()}'")
                s.backup(d)
            finally:
                d.close()
                s.close()
            os.replace(tmp, dst)
            done = True
        except Exception as e:
            log(f"Respaldo en línea de Rekordbox falló ({e!r}); uso copia de archivos")
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if not done:
        shutil.copy2(src, dst)
        if wal.exists() and wal.stat().st_size > 0:  # que el respaldo no pierda lo que estaba en el diario
            shutil.copy2(wal, dst.with_name(dst.name + "-wal"))
    # se conservan los 5 más recientes y, además, el PRIMERO de cada uno de los últimos 7 días: varias
    # operaciones seguidas ya no se llevan el respaldo de antes de empezar
    olds = sorted(RB_DIR.glob("master.backup.brainorder-*.db"), key=_backup_stamp)
    keep = set(olds[-5:])
    first_of_day = {}
    for b in olds:
        st = _backup_stamp(b)
        if (datetime.now() - st).days < 7:
            first_of_day.setdefault(st.date(), b)
    keep |= set(first_of_day.values())
    for old in [b for b in olds if b not in keep]:
        for f in (old, old.with_name(old.name + "-wal")):
            try:
                f.unlink()
            except OSError:
                pass
    return dst


def _backup_stamp(p):
    """Fecha del respaldo según su nombre (la fecha del archivo es la de master.db: copy2 la conserva)."""
    try:
        return datetime.strptime(p.name.split("-", 1)[1][:15], "%Y%m%d-%H%M%S")
    except (IndexError, ValueError):
        return datetime.fromtimestamp(0)


def recent_backup(minutes=60):
    """¿Hay un respaldo de BrainOrder hecho hace menos de X minutos? (el automático no repite 200 MB cada 5 min)"""
    newest = max((_backup_stamp(p) for p in RB_DIR.glob("master.backup.brainorder-*.db")), default=None)
    return bool(newest) and (datetime.now() - newest).total_seconds() < minutes * 60


def content_by_path(db, path):
    """La pista de la colección con esa ruta, aunque Rekordbox la haya guardado con barras de más
    («//Users/...»). Sin esto BrainOrder no la encontraba: al mover el archivo no corregía la ruta (y la
    canción quedaba perdida) y al sincronizar la agregaba otra vez."""
    want = rb_path(path)
    c = db.get_content(FolderPath=want).first()
    if c is not None or not want.startswith("/"):
        return c
    c = db.get_content(FolderPath="/" + want).first()
    if c is not None:
        return c
    try:  # último recurso: cualquier variante con barras repetidas
        from pyrekordbox.masterdb import models as M
    except ImportError:  # pyrekordbox 0.4
        from pyrekordbox.db6 import tables as M
    name = want.rsplit("/", 1)[-1]
    import os as _os
    same = (lambda a, b: a.lower() == b.lower()) if _os.name == "nt" else (lambda a, b: a == b)
    for x in db.query(M.DjmdContent).filter(M.DjmdContent.FileNameL == name):
        if x.FolderPath and same(rb_path(x.FolderPath), want):
            return x
    if _os.name == "nt":  # Windows: el nombre del archivo pudo cambiar solo de mayúsculas
        for x in db.query(M.DjmdContent).filter(M.DjmdContent.FileNameL.ilike(name)):
            if x.FolderPath and same(rb_path(x.FolderPath), want):
                return x
    return None


def _find_child(db, parent_id, name, attribute):
    for p in db.get_playlist(ParentID=parent_id, Name=name):
        if (p.Attribute or 0) == attribute:
            return p
    return None


def sync(analysis, cfg, progress=None):
    try:
        try:
            from pyrekordbox import MasterDatabase as Rekordbox6Database
        except ImportError:
            from pyrekordbox import Rekordbox6Database
    except Exception as e:
        raise RekordboxError(f"Falta pyrekordbox ({e}). Vuelve a correr el instalador.")
    if rekordbox_running():
        raise RekordboxError("Rekordbox está abierto. Ciérralo y vuelve a darle a Organizar.")

    bk = backup()
    if progress:
        progress(f"Respaldo creado: {bk.name}")
    path = RB_DIR / "master.db"
    try:
        db = Rekordbox6Database(path=path)
    except Exception as e:
        raise RekordboxError(f"No pude abrir la librería de Rekordbox: {e}")

    stats = {"playlists_created": 0, "playlists_updated": 0, "tracks_added": 0, "backup": bk.name}
    try:
        folder_name = cfg.get("rekordbox_folder", "Spotify")
        root = _find_child(db, "root", folder_name, 1)
        if root is None:
            root = db.create_playlist_folder(folder_name)
            stats["playlists_created"] += 1

        artist_cache = {}

        def artist_id(name):
            if not name:
                return None
            if name not in artist_cache:
                a = db.get_artist(Name=name).first()
                if a is None:
                    a = db.add_artist(name)
                artist_cache[name] = a.ID
            return artist_cache[name]

        analysis = [p for p in analysis if not p.get("pending")]  # sin analizar: no se tocan
        # playlists que manda Rekordbox (elegiste mantener tus cambios) o con cambios tuyos sin decidir
        skip = set(cfg.get("rb_keep") or []) | set(cfg.get("_rb_pending") or [])
        stats["skipped"] = [p["name"] for p in analysis if p["id"] in skip]
        analysis = [p for p in analysis if p["id"] not in skip]
        baseline = {}
        for i, pl in enumerate(analysis, 1):
            if progress:
                progress(f"Rekordbox {i}/{len(analysis)}: {pl['name']}")
            desired, seen = [], set()
            for r in pl["tracks"]:
                if r["status"] in ("ok", "elsewhere") and r["source"] and r["source"] not in seen:
                    seen.add(r["source"])
                    desired.append(r)
            playlist = _find_child(db, root.ID, pl["name"], 0)
            if playlist is None:
                playlist = db.create_playlist(pl["name"], parent=root)
                stats["playlists_created"] += 1
            current = [rb_path(s.Content.FolderPath) if s.Content else None
                       for s in sorted(playlist.Songs, key=lambda s: s.TrackNo or 0)]
            baseline[str(playlist.ID)] = {"pid": pl["id"], "name": pl["name"], "paths": [r["source"] for r in desired]}
            if current == [rb_path(r["source"]) for r in desired]:
                continue
            for song in list(playlist.Songs):
                db.remove_from_playlist(playlist, song)
            for r in desired:
                content = content_by_path(db, r["source"])
                if content is None:
                    try:
                        content = db.add_content(
                            r["source"], Title=r["name"],
                            ArtistID=artist_id(r["artists"][0] if r["artists"] else ""))
                        stats["tracks_added"] += 1
                    except ValueError as e:
                        log(f"Rekordbox no aceptó {r['source']}: {e}")
                        continue
                db.add_to_playlist(playlist, content)
            stats["playlists_updated"] += 1
        db.commit()
        stats["baseline"] = baseline
    except RekordboxError:
        db.rollback()
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        log(f"Error en Rekordbox: {e!r}")
        raise RekordboxError(f"Error escribiendo en Rekordbox (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    log(f"Rekordbox: {stats}")
    return stats


def edit_playlists(cfg, renames=None, deletes=None):
    """Renombra / elimina playlists dentro de la carpeta de BrainOrder en Rekordbox (con respaldo).
    renames: {nombre_viejo: nombre_nuevo}; deletes: [nombre]. -> {"renamed", "deleted", "backup"}"""
    renames, deletes = dict(renames or {}), list(deletes or [])
    if not renames and not deletes:
        return None
    try:
        from pyrekordbox import MasterDatabase as Rekordbox6Database
    except ImportError:
        from pyrekordbox import Rekordbox6Database
    if rekordbox_running():
        raise RekordboxError("Rekordbox está abierto. Ciérralo y vuelve a intentarlo.")
    db = Rekordbox6Database(path=RB_DIR / "master.db")
    try:
        root = _find_child(db, "root", cfg.get("rekordbox_folder") or "BrainOrder", 1)
        todo = root is not None and (any(_find_child(db, root.ID, o, 0) for o in renames) or
                                     any(_find_child(db, root.ID, n, 0) for n in deletes))
        if not todo:
            return {"renamed": 0, "deleted": 0, "backup": None}
    except Exception:
        db.close()
        raise
    db.close()
    bk = backup()
    db = Rekordbox6Database(path=RB_DIR / "master.db")
    out = {"renamed": 0, "deleted": 0, "backup": bk.name}
    try:
        root = _find_child(db, "root", cfg.get("rekordbox_folder") or "BrainOrder", 1)
        for old, new in renames.items():
            p = _find_child(db, root.ID, old, 0)
            if p is None:
                continue
            if _find_child(db, root.ID, new, 0) is not None:
                db.delete_playlist(p)  # ya hay una con el nombre nuevo (fusionar): queda esa
                out["deleted"] += 1
            else:
                db.rename_playlist(p, new)
                out["renamed"] += 1
        for name in deletes:
            p = _find_child(db, root.ID, name, 0)
            if p is not None:
                db.delete_playlist(p)
                out["deleted"] += 1
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        log(f"Error editando playlists en Rekordbox: {e!r}")
        raise RekordboxError(f"No pude cambiar las playlists en Rekordbox (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    return out


def root_children(cfg, name):
    con = connect_ro()
    try:
        alive = "COALESCE(rb_local_deleted, 0) = 0"
        row = con.execute(f"SELECT ID FROM djmdPlaylist WHERE ParentID = 'root' AND Name = ? AND Attribute = 1 AND {alive}",
                          (name,)).fetchone()
        if row is None:
            return None
        return [r[0] for r in con.execute(f"SELECT Name FROM djmdPlaylist WHERE ParentID = ? AND {alive}", (row[0],))]
    finally:
        con.close()


def rename_root(cfg, old, new):
    """Renombra la carpeta de BrainOrder (las playlists conservan su id). Si ya existía una carpeta con el
    nombre nuevo (por ejemplo la creó un Organizar), se reemplaza por la vieja, que es la que tiene tu historia."""
    try:
        from pyrekordbox import MasterDatabase as Rekordbox6Database
    except ImportError:
        from pyrekordbox import Rekordbox6Database
    if rekordbox_running():
        raise RekordboxError("Rekordbox está abierto.")
    if root_children(cfg, old) is None:
        return {"renamed": False}
    bk = backup()
    db = Rekordbox6Database(path=RB_DIR / "master.db")
    out = {"renamed": False, "replaced": 0, "backup": bk.name, "deleted_ids": []}
    try:
        src = _find_child(db, "root", old, 1)
        dup = _find_child(db, "root", new, 1)
        if dup is not None:
            for p in list(db.get_playlist(ParentID=dup.ID)):
                out["deleted_ids"].append(str(p.ID))
                db.delete_playlist(p)
                out["replaced"] += 1
            db.delete_playlist(dup)
        db.rename_playlist(src, new)
        db.commit()
        out["renamed"] = True
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise RekordboxError(f"No pude renombrar la carpeta en Rekordbox (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    return out


def root_folders(cfg):
    """{nombre de carpeta en la raíz: [nombres de lo que tiene adentro]}"""
    con = connect_ro()
    try:
        alive = "COALESCE(rb_local_deleted, 0) = 0"
        out = {}
        for fid, name in con.execute(f"SELECT ID, Name FROM djmdPlaylist WHERE ParentID = 'root' AND Attribute = 1 AND {alive}"):
            out.setdefault(name, []).extend(r[0] for r in con.execute(f"SELECT Name FROM djmdPlaylist WHERE ParentID = ? AND {alive}", (fid,)))
        return out
    finally:
        con.close()
