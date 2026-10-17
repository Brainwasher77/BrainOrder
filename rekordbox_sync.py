"""Replica las playlists de Spotify dentro de Rekordbox (carpeta 'Spotify' por defecto).

- Escribe directamente en master.db con pyrekordbox.
- Exige que Rekordbox esté cerrado.
- Hace copia de seguridad de master.db antes de cualquier cambio.
- Cada playlist queda con las canciones en el mismo orden que en Spotify
  (las que ya tienes, estén donde estén; un solo archivo aunque esté en varias playlists).
"""
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
    try:
        from pyrekordbox.utils import get_rekordbox_pid
        return bool(get_rekordbox_pid())
    except Exception:
        return False


def backup():
    src = RB_DIR / "master.db"
    if not src.exists():
        raise RekordboxError(f"No encontré la librería de Rekordbox en {src}")
    dst = RB_DIR / f"master.backup.brainorder-{datetime.now():%Y%m%d-%H%M%S}.db"
    shutil.copy2(src, dst)
    # conservar solo los 5 respaldos más recientes de BrainOrder (antes se llamaba SpotiSync)
    olds = sorted(list(RB_DIR.glob("master.backup.spotisync-*.db")) + list(RB_DIR.glob("master.backup.brainorder-*.db")),
                  key=lambda p: p.stat().st_mtime)
    for old in olds[:-5]:
        try:
            old.unlink()
        except Exception:
            pass
    return dst


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
            if current == [rb_path(r["source"]) for r in desired]:
                continue
            for song in list(playlist.Songs):
                db.remove_from_playlist(playlist, song)
            for r in desired:
                content = db.get_content(FolderPath=rb_path(r["source"])).first()
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
