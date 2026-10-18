"""Pasa a Rekordbox lo que analizó Mixed In Key: key (tonalidad) y energía.

- Solo canciones que ya están en tu colección de Rekordbox y que tienen datos de MIK en el archivo.
- Key: se escribe en la columna Key de Rekordbox en su notación (Am, F#m, Db…), así Rekordbox la
  muestra también en Alphanumeric/Camelot. MIK siempre gana sobre lo que haya.
- Energía: Rekordbox no tiene campo de energía; va al Comentario con el formato de MIK
  («8A - Energy 6»), pero SOLO si el comentario está vacío o ya era de MIK (tus comentarios no se tocan).
- No toca BPM, grid ni cues (eso es de Rekordbox).
- Rekordbox debe estar cerrado para escribir; antes se respalda master.db.
"""
import re
from uuid import uuid4

import armonia
from config import log
from plataforma import native

# Camelot -> nombre que usa Rekordbox
RB_NAME = {
    "1A": "Abm", "2A": "Ebm", "3A": "Bbm", "4A": "Fm", "5A": "Cm", "6A": "Gm",
    "7A": "Dm", "8A": "Am", "9A": "Em", "10A": "Bm", "11A": "F#m", "12A": "Dbm",
    "1B": "B", "2B": "F#", "3B": "Db", "4B": "Ab", "5B": "Eb", "6B": "Bb",
    "7B": "F", "8B": "C", "9B": "G", "10B": "D", "11B": "A", "12B": "E",
}
_MIK_COMMENT = re.compile(r"^\s*(0?(1[0-2]|[1-9])[AB])?\s*(-\s*)?(Energy\s*\d{1,2})?\s*$", re.I)


def comment_for(key, energy, fmt="key_energy"):
    if fmt == "none":
        return None
    if fmt == "energy":
        return f"Energy {energy}" if energy else None
    if key and energy:
        return f"{key} - Energy {energy}"
    return f"Energy {energy}" if energy else None


def _comment_is_ours(c):
    """Vacío o con el formato que escribe MIK/BrainOrder: se puede reemplazar."""
    return not (c or "").strip() or bool(_MIK_COMMENT.match(c))


def _rb_key_camelot(scale):
    return armonia.to_camelot(scale) if scale else None


def plan_and_apply(db, cfg, apply=False, progress=None, info=None):
    """Recorre la colección. Devuelve los cambios (y los aplica si apply=True; NO hace commit)."""
    info = info or armonia.info
    fmt = cfg.get("rb_mik_comment", "key_energy")
    keys = {k.ScaleName: k for k in db.get_key()}
    changes = []
    contents = list(db.get_content())
    for n, c in enumerate(contents, 1):
        if progress and n % 300 == 0:
            progress(f"Revisando Rekordbox {n}/{len(contents)}…", n / len(contents))
        path = c.FolderPath
        if not path:
            continue
        h = info(native(path))
        if not h or not h.get("mik"):
            continue
        new_key = RB_NAME.get(h.get("key")) if h.get("key_mik") else None
        cur_scale = c.Key.ScaleName if c.Key else None
        ch = {}
        if new_key and _rb_key_camelot(cur_scale) != h["key"]:
            ch["key"] = (cur_scale, new_key)
        want = comment_for(h.get("key") if h.get("key_mik") else None, h.get("energy"), fmt)
        if want and (c.Commnt or "").strip() != want and _comment_is_ours(c.Commnt):
            ch["comment"] = (c.Commnt or "", want)
        if not ch:
            continue
        changes.append({"id": c.ID, "title": c.Title, "path": native(path), **{k: v for k, v in ch.items()}})
        if apply:
            if "key" in ch:
                k = keys.get(new_key)
                if k is None:
                    import pyrekordbox.masterdb.models as M
                    k = M.DjmdKey.create(ID=str(db.generate_unused_id(M.DjmdKey)), ScaleName=new_key,
                                         Seq=None, UUID=str(uuid4()))
                    db.add(k)
                    db.flush()
                    keys[new_key] = k
                c.KeyID = k.ID
            if "comment" in ch:
                c.Commnt = want
    return changes


def run(cfg, apply=False, progress=None):
    """Abre la librería real (para aplicar: Rekordbox cerrado y con respaldo) o una copia (para ver)."""
    import rekordbox_sync
    import rb_cambios  # noqa: F401  (misma forma de abrir)
    try:
        from pyrekordbox import MasterDatabase as DB
    except ImportError:  # pragma: no cover
        from pyrekordbox import Rekordbox6Database as DB
    path = rekordbox_sync.RB_DIR / "master.db"
    if not path.exists():
        raise rekordbox_sync.RekordboxError("No encontré la librería de Rekordbox.")
    if not apply:
        import shutil
        import tempfile
        from pathlib import Path
        tmp = tempfile.mkdtemp(prefix="brainorder-mik-")
        try:
            for suf in ("", "-wal", "-shm"):
                f = path.with_name("master.db" + suf)
                if f.exists():
                    shutil.copy2(f, Path(tmp) / ("master.db" + suf))
            db = DB(path=Path(tmp) / "master.db")
            try:
                return {"changes": plan_and_apply(db, cfg, False, progress)}
            finally:
                db.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if rekordbox_sync.rekordbox_running():
        raise rekordbox_sync.RekordboxError("Rekordbox está abierto. Ciérralo para pasarle la key y energía de Mixed In Key.")
    db = DB(path=path)
    try:
        changes = plan_and_apply(db, cfg, False, progress)
        if not changes:
            return {"changes": [], "backup": None}
        bk = rekordbox_sync.backup().name
        plan_and_apply(db, cfg, True, progress)
        db.commit()
        armonia.save()
        log(f"MIK -> Rekordbox: {len(changes)} canciones actualizadas (respaldo {bk})")
        return {"changes": changes, "backup": bk}
    except rekordbox_sync.RekordboxError:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise rekordbox_sync.RekordboxError(f"No pude pasar los datos de MIK a Rekordbox (no se guardó nada): {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
