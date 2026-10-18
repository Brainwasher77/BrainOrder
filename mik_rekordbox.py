"""Pasa a Rekordbox lo que analizó Mixed In Key: key (tonalidad), energía y hot cues.

- Solo canciones que ya están en tu colección de Rekordbox y que tienen datos de MIK en el archivo.
- Key: se escribe en la columna Key de Rekordbox en su notación (Am, F#m, Db…), así Rekordbox la
  muestra también en Alphanumeric/Camelot. MIK siempre gana sobre lo que haya.
- Energía: Rekordbox no tiene campo de energía; va al Comentario con el formato de MIK
  («8A - Energy 6»), pero SOLO si el comentario está vacío o ya era de MIK (tus comentarios no se tocan).
- Hot cues de MIK (A, B, C…): solo en canciones que todavía no tienen ningún hot cue en Rekordbox
  (tus cues nunca se pisan). Se escriben en djmdCue y en contentCue (la copia que usa Rekordbox 7).
  FLAC: se calcula el frame como hace Rekordbox; MP3 VBR: se saltan (Rekordbox las ubica distinto).
- No toca BPM, grid ni memory cues.
- Rekordbox debe estar cerrado para escribir; antes se respalda master.db.
"""
import json
import re
from datetime import datetime, timezone
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


HOT_KIND = [1, 2, 3, 5, 6, 7, 8, 9]  # hot cue A..H en djmdCue.Kind (0 = memory cue, 4 no se usa)


def _is_vbr_mp3(path):
    try:
        import mutagen
        from mutagen.mp3 import BitrateMode
        m = mutagen.File(path)
        return getattr(m.info, "bitrate_mode", None) == BitrateMode.VBR
    except Exception:
        return False


def cue_rows(path, cues):
    """[[nombre, ms]] de MIK -> datos para djmdCue (None si ese formato no se puede ubicar bien)."""
    import mik_dj
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "mp3" and _is_vbr_mp3(path):
        return None
    out = []
    for i, (name, ms) in enumerate(cues[:8]):
        ms = int(round(ms))
        row = {"InMsec": ms, "InFrame": ms * 150 // 1000, "Kind": HOT_KIND[i]}
        if ext == "flac":
            seek = mik_dj.flac_seek_info(path, ms)
            if not seek:
                return None
            row["InPointSeekInfo"], row["OutPointSeekInfo"] = seek, "0,0,0"
        out.append(row)
    return out


def _iso(dt):
    """Fecha local de la base -> «2026-09-24T20:05:51.224+00:00» (como la guarda contentCue)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}+00:00"


def rebuild_content_cue(db, content):
    import pyrekordbox.masterdb.models as M
    cues = db.query(M.DjmdCue).filter(M.DjmdCue.ContentID == content.ID).all()
    items = []
    for c in sorted(cues, key=lambda x: (x.Kind or 0, x.InMsec or 0)):
        d = {"ID": c.ID, "ContentID": c.ContentID, "ContentUUID": c.ContentUUID, "InMsec": c.InMsec,
             "InFrame": c.InFrame, "InMpegFrame": c.InMpegFrame, "InMpegAbs": c.InMpegAbs}
        if c.InPointSeekInfo is not None:
            d["InPointSeekInfo"] = c.InPointSeekInfo
        d.update({"OutMsec": c.OutMsec, "OutFrame": c.OutFrame, "OutMpegFrame": c.OutMpegFrame,
                  "OutMpegAbs": c.OutMpegAbs})
        if c.OutPointSeekInfo is not None:
            d["OutPointSeekInfo"] = c.OutPointSeekInfo
        for k in ("Comment", "ColorTableIndex", "ActiveLoop", "BeatLoopSize", "CueMicrosec"):
            if getattr(c, k, None) is not None:
                d[k] = getattr(c, k)
        d.update({"Kind": c.Kind, "Color": c.Color, "UUID": c.UUID,
                  "created_at": _iso(c.created_at), "updated_at": _iso(c.updated_at)})
        items.append(d)
    blob = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    cc = db.query(M.ContentCue).filter(M.ContentCue.ContentID == content.ID).first()
    now = datetime.now()
    if cc is None:
        cc = M.ContentCue(ID=content.UUID or str(uuid4()), ContentID=content.ID, Cues=blob,
                          rb_cue_count=len(items), UUID=str(uuid4()), created_at=now, updated_at=now)
        db.add(cc)
    else:
        cc.Cues, cc.rb_cue_count, cc.updated_at = blob, len(items), now


def add_hot_cues(db, content, rows):
    import pyrekordbox.masterdb.models as M
    now = datetime.now()
    for r in rows:
        cue = M.DjmdCue(ID=str(db.generate_unused_id(M.DjmdCue)), ContentID=content.ID,
                        InMsec=r["InMsec"], InFrame=r["InFrame"], InMpegFrame=0, InMpegAbs=0,
                        OutMsec=-1, OutFrame=0, OutMpegFrame=0, OutMpegAbs=0, Kind=r["Kind"], Color=-1,
                        InPointSeekInfo=r.get("InPointSeekInfo"), OutPointSeekInfo=r.get("OutPointSeekInfo"),
                        ContentUUID=content.UUID, UUID=str(uuid4()), created_at=now, updated_at=now)
        db.add(cue)
        db.flush()
    rebuild_content_cue(db, content)


def plan_and_apply(db, cfg, apply=False, progress=None, info=None):
    """Recorre la colección. Devuelve los cambios (y los aplica si apply=True; NO hace commit)."""
    import pyrekordbox.masterdb.models as M
    info = info or armonia.info
    fmt = cfg.get("rb_mik_comment", "key_energy")
    want_cues = cfg.get("rb_mik_cues", True)
    keys = {k.ScaleName: k for k in db.get_key()}
    has_hot = {c.ContentID for c in db.query(M.DjmdCue).filter(M.DjmdCue.Kind > 0)} if want_cues else set()
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
        rows = None
        if want_cues and h.get("cues") and str(c.ID) not in has_hot:
            rows = cue_rows(native(path), h["cues"])
            if rows:
                ch["cues"] = len(rows)
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
            if rows:
                add_hot_cues(db, c, rows)
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
        raise rekordbox_sync.RekordboxError("Rekordbox está abierto. Ciérralo para pasarle los datos de Mixed In Key.")
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
