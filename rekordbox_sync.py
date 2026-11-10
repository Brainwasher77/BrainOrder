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


def _our_tree(db, cfg, create=True):
    """La carpeta de BrainOrder (aunque le hayas cambiado el nombre en Rekordbox) y TODAS las playlists que
    tiene adentro, también las que metiste en subcarpetas. -> (carpeta, {id: {"name", "folder"}}, creada?)"""
    import rb_arbol
    import rb_cambios
    rows = rb_arbol.db_rows(db)
    name = cfg.get("rekordbox_folder") or "BrainOrder"
    rid, _n, _ren = rb_arbol.locate(rows, [name], list(rb_cambios.load_baseline()))
    root = db.get_playlist(ID=rid) if rid else None
    if root is None:
        if not create:
            return None, {}, False
        return db.create_playlist_folder(name), {}, True
    return root, rb_arbol.playlists(rows, rid), False


def _pick(inside, name, prefer=None, loose_only=True):
    """La playlist de BrainOrder dentro del árbol: la de la foto (prefer = su id, esté donde esté, también si la
    metiste en una subcarpeta) o, si no, una SUELTA con ese nombre. Nunca se casa por nombre con una playlist
    de tus subcarpetas: puede ser otra distinta que se llama igual (MGNO/Pop latino no es tu «Pop latino»)."""
    if prefer and str(prefer) in inside:
        return str(prefer)
    hits = [rid for rid, v in inside.items() if v["name"] == name and (not loose_only or not v["folder"])]
    return sorted(hits)[0] if hits else None


def _twins(db, root, inside, pid_of):
    """Playlists repetidas por el error de antes (la movías a una subcarpeta y Organizar volvía a crear una
    suelta): SOLO cuando las dos son la MISMA playlist de BrainOrder (mismo id en la foto). Se queda la de tu
    subcarpeta, se le suma lo que solo tenía la suelta y la suelta se quita. -> [ids quitados]"""
    out = []
    by_pid = {}
    for rid, v in inside.items():
        if pid_of.get(rid):
            by_pid.setdefault(pid_of[rid], []).append(rid)
    for _pid, ids in by_pid.items():
        loose = [r for r in ids if not inside[r]["folder"]]
        nested = [r for r in ids if inside[r]["folder"]]
        if not loose or not nested:
            continue
        keep = nested[0]
        kp = db.get_playlist(ID=keep)
        have = {str(s.ContentID) for s in kp.Songs}
        for r in loose:
            p = db.get_playlist(ID=r)
            if p is None:
                continue
            for s in sorted(p.Songs, key=lambda s: s.TrackNo or 0):
                if s.Content is not None and str(s.ContentID) not in have:
                    db.add_to_playlist(kp, s.Content)
                    have.add(str(s.ContentID))
            db.delete_playlist(p)
            out.append(r)
            inside.pop(r, None)
    return out


def _k(p):
    """Clave para comparar rutas (Rekordbox guarda «/» y a veces barras de más; Windows no distingue mayúsculas)."""
    k = rb_path(p or "")
    while "//" in k:
        k = k.replace("//", "/")
    return k.casefold() if os.name == "nt" else k


def merge_plan(current, desired, previous=None):
    """Rekordbox manda. current: rutas que hay ahora en la playlist de Rekordbox (en su orden); desired: las
    que BrainOrder quiere; previous: las que dejó BrainOrder la última vez (la foto; None si no hay).
      - lo que agregaste en Rekordbox se queda, aunque la plataforma no lo tenga;
      - lo que quitaste en Rekordbox NO vuelve a entrar;
      - lo que la plataforma quitó (estaba la última vez y ya no) sale;
      - lo nuevo de la plataforma entra al final;
      - el orden de Rekordbox no se toca.
    -> {"remove": [claves], "add": [claves en el orden de desired], "final": [rutas en el orden final]}"""
    cur_k = [_k(p) for p in current if p]
    des = {}
    for p in desired:
        des.setdefault(_k(p), p)
    prev = {_k(p) for p in previous} if previous is not None else set(cur_k)
    cur_set = set(cur_k)
    remove = {k for k in cur_k if k not in des and k in prev}
    add = [k for k in des if k not in cur_set and k not in prev]
    final = [p for p in current if p and _k(p) not in remove] + [des[k] for k in add]
    return {"remove": sorted(remove), "add": add, "final": final}


def _content_for(db, r, artist_id, stats):
    content = content_by_path(db, r["source"])
    if content is None:
        try:
            content = db.add_content(r["source"], Title=r["name"],
                                     ArtistID=artist_id(r["artists"][0] if r["artists"] else ""))
            stats["tracks_added"] += 1
        except ValueError as e:
            log(f"Rekordbox no aceptó {r['source']}: {e}")
            return None
    return content


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
        root, inside, made = _our_tree(db, cfg)
        if made:
            stats["playlists_created"] += 1
        base_ids, pid_of = {}, {}
        for rid, b in (cfg.get("_rb_base") or {}).items():
            if b.get("pid"):
                pid_of[str(rid)] = b["pid"]
                # la de una subcarpeta tuya manda sobre una suelta repetida
                if b["pid"] not in base_ids or (str(rid) in inside and inside[str(rid)]["folder"]):
                    base_ids[b["pid"]] = str(rid)
        gone = _twins(db, root, inside, pid_of)
        if gone:
            stats["twins_removed"] = len(gone)
            stats["twins_ids"] = gone

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

        master = bool(cfg.get("rb_master", True))
        base_all = cfg.get("_rb_base") or {}
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
            # dentro de la carpeta, donde la hayas puesto (también en una subcarpeta tuya): no se crea otra
            hit = _pick(inside, pl["name"], base_ids.get(pl["id"]))
            playlist = db.get_playlist(ID=hit) if hit else None
            created = playlist is None
            if created:
                playlist = db.create_playlist(pl["name"], parent=root)
                inside[str(playlist.ID)] = {"name": pl["name"], "folder": []}
                stats["playlists_created"] += 1
            songs = sorted(playlist.Songs, key=lambda s: s.TrackNo or 0)
            current = [rb_path(s.Content.FolderPath) if s.Content else None for s in songs]
            if master and not created:
                # Rekordbox manda: se conserva su orden y lo que hiciste ahí; solo entra lo nuevo de la
                # plataforma (al final) y sale lo que la plataforma quitó desde la última vez
                prev = (base_all.get(str(playlist.ID)) or {}).get("paths")
                plan = merge_plan(current, [r["source"] for r in desired], prev)
                baseline[str(playlist.ID)] = {"pid": pl["id"], "name": pl["name"],
                                              "paths": [plataforma.native(x) for x in plan["final"]]}
                if not plan["remove"] and not plan["add"]:
                    continue
                gone = set(plan["remove"])
                for song in songs:
                    if song.Content and _k(song.Content.FolderPath) in gone:
                        db.remove_from_playlist(playlist, song)
                by_key = {_k(r["source"]): r for r in desired}
                for key in plan["add"]:
                    r = by_key[key]
                    content = _content_for(db, r, artist_id, stats)
                    if content is not None:
                        db.add_to_playlist(playlist, content)
                stats["playlists_updated"] += 1
                stats["kept_order"] = stats.get("kept_order", 0) + 1
                continue
            baseline[str(playlist.ID)] = {"pid": pl["id"], "name": pl["name"], "paths": [r["source"] for r in desired]}
            if current == [rb_path(r["source"]) for r in desired]:
                continue
            for song in list(playlist.Songs):
                db.remove_from_playlist(playlist, song)
            for r in desired:
                content = _content_for(db, r, artist_id, stats)
                if content is not None:
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
        root, inside, _m = _our_tree(db, cfg, create=False)
        todo = root is not None and (any(_pick(inside, o, loose_only=False) for o in renames) or any(_pick(inside, n) for n in deletes))
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
        root, inside, _m = _our_tree(db, cfg, create=False)
        for old, new in renames.items():
            hit = _pick(inside, old)
            p = db.get_playlist(ID=hit) if hit else None
            if p is None:
                continue
            if _pick(inside, new) is not None:
                db.delete_playlist(p)  # ya hay una con el nombre nuevo (fusionar): queda esa
                inside.pop(hit, None)
                out["deleted"] += 1
            else:
                db.rename_playlist(p, new)  # se queda en la subcarpeta donde la tengas
                inside[hit]["name"] = new
                out["renamed"] += 1
        for name in deletes:
            hit = _pick(inside, name)
            p = db.get_playlist(ID=hit) if hit else None
            if p is not None:
                db.delete_playlist(p)
                inside.pop(hit, None)
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


def adopt(cfg, jobs, progress=None):
    """Lleva a la carpeta de BrainOrder las playlists de Rekordbox que agregaste a BrainOrder, para no
    tenerlas dos veces. jobs: [{"ref": id en Rekordbox, "name": nombre en BrainOrder, "pid", "mode"}]
      mode "move":   se mueve a la carpeta (y toma el nombre de BrainOrder). Si ahí ya hay una con ese
                     nombre, se le suman las canciones que no tenga y la original se quita.
      mode "delete": ya la sumaste a otra playlist: la original se quita (las canciones siguen en tu
                     colección, con sus cues; solo se quita la playlist).
    Rekordbox cerrado y respaldo antes. -> {"moved", "deleted", "merged", "missing", "baseline", "backup"}"""
    try:
        from pyrekordbox import MasterDatabase as Rekordbox6Database
    except ImportError:
        from pyrekordbox import Rekordbox6Database
    if rekordbox_running():
        raise RekordboxError("Rekordbox está abierto. Ciérralo para mover tus playlists a la carpeta de BrainOrder.")
    bk = backup()
    db = Rekordbox6Database(path=RB_DIR / "master.db")
    out = {"moved": 0, "deleted": 0, "merged": 0, "missing": 0, "baseline": {}, "backup": bk.name, "done": []}
    try:
        root, inside, _m = _our_tree(db, cfg)
        for j in jobs:
            try:
                pl = db.get_playlist(ID=str(j["ref"]))
            except Exception:
                pl = None
            if pl is None:
                out["missing"] += 1
                out["done"].append(j)  # ya no existe: no hay nada que mover
                continue
            if j.get("mode") == "delete":
                db.delete_playlist(pl)
                out["deleted"] += 1
                out["done"].append(j)
                continue
            name = j.get("name") or pl.Name
            target = pl
            hit = _pick(inside, name)
            clash = db.get_playlist(ID=hit) if hit else None
            if clash is not None and str(clash.ID) != str(pl.ID):
                have = {str(s.ContentID) for s in clash.Songs}
                for s in sorted(pl.Songs, key=lambda s: s.TrackNo or 0):
                    if s.Content is not None and str(s.ContentID) not in have:
                        db.add_to_playlist(clash, s.Content)
                        have.add(str(s.ContentID))
                db.delete_playlist(pl)
                target = clash
                out["merged"] += 1
            else:
                if str(pl.ID) not in inside and str(pl.ParentID) != str(root.ID):  # si ya está en tu árbol, ahí se queda
                    if hasattr(db, "move_playlist"):
                        db.move_playlist(pl, parent=root)
                    else:  # pragma: no cover (pyrekordbox viejo)
                        pl.ParentID = root.ID
                if pl.Name != name:
                    db.rename_playlist(pl, name)
                inside.setdefault(str(pl.ID), {"name": name, "folder": []})["name"] = name
                out["moved"] += 1
            songs = sorted(target.Songs, key=lambda s: s.TrackNo or 0)
            out["baseline"][str(target.ID)] = {
                "pid": j.get("pid"), "name": name,
                "paths": [plataforma.native(s.Content.FolderPath) for s in songs if s.Content and s.Content.FolderPath]}
            out["done"].append(j)
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        log(f"Error moviendo playlists a la carpeta de BrainOrder: {e!r}")
        raise RekordboxError(f"No pude mover las playlists en Rekordbox (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    log(f"Rekordbox: playlists llevadas a «{cfg.get('rekordbox_folder')}»: {out['moved']} movidas, "
        f"{out['merged']} juntadas, {out['deleted']} quitadas (respaldo {bk.name})")
    return out


def lift_folders(cfg, folder_ids, drop_ids):
    """Desarmar playlists que se tragaron una carpeta: la carpeta (con sus subcarpetas y playlists, tal cual)
    pasa dentro de la carpeta de BrainOrder y la playlist global se quita (sus canciones siguen en la
    colección). Rekordbox cerrado y respaldo antes. -> {"moved", "deleted", "backup"}"""
    try:
        from pyrekordbox import MasterDatabase as Rekordbox6Database
    except ImportError:
        from pyrekordbox import Rekordbox6Database
    if rekordbox_running():
        raise RekordboxError("Rekordbox está abierto. Ciérralo para desarmar la playlist.")
    bk = backup()
    db = Rekordbox6Database(path=RB_DIR / "master.db")
    out = {"moved": 0, "deleted": 0, "backup": bk.name}
    try:
        root, _inside, _m = _our_tree(db, cfg)
        for pid in drop_ids or []:
            p = db.get_playlist(ID=str(pid))
            if p is not None and (p.Attribute or 0) == 0:
                db.delete_playlist(p)
                out["deleted"] += 1
        for fid in folder_ids or []:
            f = db.get_playlist(ID=str(fid))
            if f is None or str(f.ParentID) == str(root.ID):
                continue
            if _find_child(db, root.ID, f.Name, 1) is not None:
                raise RekordboxError(f"Ya hay una carpeta «{f.Name}» dentro de «{root.Name}».")
            db.move_playlist(f, parent=root)
            out["moved"] += 1
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        log(f"Error desarmando en Rekordbox: {e!r}")
        raise RekordboxError(f"No pude hacerlo en Rekordbox (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    log(f"Rekordbox: carpetas pasadas a la de BrainOrder {out}")
    return out


# ------------------------------------------------------------------ recuperar playlists de un respaldo
def list_backups():
    """Respaldos de la librería que hay al lado de master.db (los de BrainOrder y los de Rekordbox), más nuevo
    primero. -> [{"name", "path", "time"}]"""
    out = []
    for p in RB_DIR.glob("master.backup*.db"):
        try:
            out.append({"name": p.name, "path": str(p), "time": p.stat().st_mtime})
        except OSError:
            pass
    return sorted(out, key=lambda x: x["name"], reverse=True)


def _open(path):
    try:
        from pyrekordbox import MasterDatabase as Rekordbox6Database
    except ImportError:
        from pyrekordbox import Rekordbox6Database
    return Rekordbox6Database(path=path)


def playlists_of(path):
    """{id: {"name", "trail": "Carpeta/Sub/Playlist", "ids": [ContentID en orden]}} de una librería."""
    db = _open(path)
    try:
        import rb_arbol
        rows = rb_arbol.db_rows(db)
        by = {str(r[0]): r for r in rows}
        out = {}
        for r in rows:
            if int(r[3] or 0) != 0:
                continue
            trail, cur, n = [r[1]], str(r[2]), 0
            while cur in by and n < 50:
                trail.append(by[cur][1])
                cur, n = str(by[cur][2]), n + 1
            out[str(r[0])] = {"name": r[1], "trail": "/".join(reversed(trail)), "ids": []}
        from sqlalchemy import text
        q = text("SELECT PlaylistID, ContentID FROM djmdSongPlaylist WHERE COALESCE(rb_local_deleted, 0) = 0 "
                 "ORDER BY PlaylistID, COALESCE(TrackNo, 0)")
        for pid, cid in db.session.execute(q):
            if str(pid) in out:
                out[str(pid)]["ids"].append(str(cid))
        return out
    finally:
        try:
            db.close()
        except Exception:
            pass


def restore_playlists(backup_path, ids):
    """Deja esas playlists con las canciones y el orden que tenían en el respaldo (las canciones que ya no
    estén en tu colección se saltan). Rekordbox cerrado y respaldo de ahora antes. -> {"restored", "missing"}"""
    if rekordbox_running():
        raise RekordboxError("Rekordbox está abierto. Ciérralo para recuperar las playlists.")
    old = playlists_of(backup_path)
    bk = backup()
    db = _open(RB_DIR / "master.db")
    out = {"restored": 0, "missing": 0, "backup": bk.name}
    try:
        for pid in ids:
            want = old.get(str(pid))
            p = db.get_playlist(ID=str(pid))
            if want is None or p is None:
                continue
            for s in list(p.Songs):
                db.remove_from_playlist(p, s)
            for cid in want["ids"]:
                try:
                    c = db.get_content(ID=cid)
                except Exception:
                    c = None
                if c is None:
                    out["missing"] += 1
                    continue
                db.add_to_playlist(p, c)
            out["restored"] += 1
        db.commit()
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        log(f"Error recuperando playlists: {e!r}")
        raise RekordboxError(f"No pude recuperarlas (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
    log(f"Rekordbox: playlists recuperadas de {Path(backup_path).name}: {out}")
    return out
