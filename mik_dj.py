"""Mixed In Key -> todos tus programas de DJ: key, energía y hot cues.

Lo que MIK dejó en cada archivo (armonia.info) se pasa a Rekordbox, Traktor, Serato y Engine DJ:
- Key: MIK siempre gana sobre lo que tenga el programa.
- Energía: al comentario («8A - Energy 6»), solo si el comentario está vacío o ya era de MIK.
- Hot cues de MIK: SOLO en canciones que todavía no tienen ningún hot cue en ese programa
  (tus cues nunca se pisan ni se mezclan). Memory cues, grid y BPM no se tocan.
  · Serato no guarda cues en su base: los lee del archivo (marcadores «Serato» que escribe el propio
    MIK si tiene activada esa opción). BrainOrder no modifica tus archivos de música, así que ahí solo
    avisa cuántas canciones tienen cues de MIK que Serato no ve.
- Cada programa tiene que estar cerrado para escribir; antes se respalda su librería.
"""
import os
import struct
import zlib
from pathlib import Path

import armonia
from config import log

PROGRAMS = ("rekordbox", "traktor", "serato", "engine")

# Camelot -> semitono (para Traktor / Engine)
_SEMI_MAJ = {v: k for k, v in armonia._MAJOR.items()}
_SEMI_MIN = {v: k for k, v in armonia._MINOR.items()}


def _camelot_parts(k):
    try:
        return int(k[:-1]), k[-1].upper()
    except Exception:
        return None, None


def traktor_key_value(k):
    """Camelot -> MUSICAL_KEY de Traktor (0-11 mayores C..B, 12-23 menores Cm..Bm)."""
    n, l = _camelot_parts(k)
    if not n:
        return None
    return _SEMI_MAJ[n] if l == "B" else 12 + _SEMI_MIN[n]


def engine_key_value(k):
    """Camelot -> Track.key de Engine DJ (0 = C, 1 = Am, 2 = G, 3 = Em… sigue la rueda)."""
    n, l = _camelot_parts(k)
    if not n:
        return None
    return ((n - 8) % 12) * 2 + (1 if l == "A" else 0)


def comment_for(key, energy, fmt="key_energy"):
    import mik_rekordbox
    return mik_rekordbox.comment_for(key, energy, fmt)


def comment_is_ours(c):
    import mik_rekordbox
    return mik_rekordbox._comment_is_ours(c)


def wanted(h, cfg):
    """De lo que leyó armonia -> (key camelot o None, comentario o None, cues [[nombre, ms]])."""
    key = h.get("key") if h.get("key_mik") else None
    com = comment_for(key, h.get("energy"), cfg.get("rb_mik_comment", "key_energy"))
    cues = (h.get("cues") or []) if cfg.get("rb_mik_cues", True) else []
    return key, com, cues


# ---------------------------------------------------------------- FLAC (Rekordbox pide dónde empieza el frame)
def _crc8(data):
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def _flac_frame_at(buf, p):
    """Número de frame si en buf[p] empieza un encabezado de frame FLAC válido (tamaño fijo)."""
    if p + 6 > len(buf) or buf[p] != 0xFF or buf[p + 1] != 0xF8:
        return None
    b2, b3 = buf[p + 2], buf[p + 3]
    bs, sr = b2 >> 4, b2 & 0x0F
    if bs == 0 or sr == 0x0F or (b3 & 1) or (b3 >> 4) > 10:
        return None
    q = p + 4
    x = buf[q]
    if x < 0x80:
        n, v = 0, x
    elif x & 0xE0 == 0xC0:
        n, v = 1, x & 0x1F
    elif x & 0xF0 == 0xE0:
        n, v = 2, x & 0x0F
    elif x & 0xF8 == 0xF0:
        n, v = 3, x & 0x07
    elif x & 0xFC == 0xF8:
        n, v = 4, x & 0x03
    elif x & 0xFE == 0xFC:
        n, v = 5, x & 0x01
    else:
        return None
    if q + 1 + n > len(buf):
        return None
    for i in range(1, n + 1):
        y = buf[q + i]
        if y & 0xC0 != 0x80:
            return None
        v = (v << 6) | (y & 0x3F)
    q += 1 + n
    q += {6: 1, 7: 2}.get(bs, 0) + {12: 1, 13: 2, 14: 2}.get(sr, 0)
    if q >= len(buf) or _crc8(buf[p:q]) != buf[q]:
        return None
    return v


def flac_seek_info(path, ms):
    """'muestra_inicio_frame,byte_desde_audio,tamaño_bloque' como lo guarda Rekordbox. None si no se puede."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"fLaC":
                return None
            minb = maxb = sr = None
            seek = []
            while True:
                h = f.read(4)
                if len(h) < 4:
                    return None
                last, typ, ln = h[0] & 0x80, h[0] & 0x7F, int.from_bytes(h[1:], "big")
                data = f.read(ln)
                if typ == 0:
                    minb, maxb = struct.unpack(">HH", data[:4])
                    sr = int.from_bytes(data[10:13], "big") >> 4
                elif typ == 3:
                    for i in range(0, len(data) - 17, 18):
                        s, o, _n = struct.unpack(">QQH", data[i:i + 18])
                        if s != 0xFFFFFFFFFFFFFFFF:
                            seek.append((s, o))
                if last:
                    break
            audio = f.tell()
            if not sr or not minb or minb != maxb:
                return None
            frame = int(ms * sr / 1000) // minb
            fsample = frame * minb
            start = max([o for s, o in seek if s <= fsample], default=0)
            f.seek(audio + start)
            pos, buf = start, b""
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    return None
                buf = buf[-32:] + chunk
                base = pos - (len(buf) - len(chunk))
                i = buf.find(b"\xff\xf8")
                while i >= 0:
                    n = _flac_frame_at(buf, i)
                    if n is not None:
                        if n == frame:
                            return f"{fsample},{base + i},{minb}"
                        if n > frame:
                            return None
                    i = buf.find(b"\xff\xf8", i + 1)
                pos += len(chunk)
                if pos - start > 64 << 20:
                    return None
    except OSError:
        return None


# ---------------------------------------------------------------- Rekordbox
def run_rekordbox(cfg, apply=False, progress=None, backup=True):
    import mik_rekordbox
    return mik_rekordbox.run(cfg, apply=apply, progress=progress, backup=backup)


# ---------------------------------------------------------------- Traktor
def plan_traktor(col, cfg, apply=False, info=None, progress=None):
    from destinos import traktor as T
    info = info or armonia.info
    import xml.etree.ElementTree as ET
    changes = []
    entries = col.coll.findall("ENTRY")
    for n, e in enumerate(entries, 1):
        if progress and n % 300 == 0:
            progress(f"Revisando Traktor {n}/{len(entries)}…", n / len(entries))
        loc = e.find("LOCATION")
        if loc is None:
            continue
        path = T._join(loc.get("VOLUME", ""), loc.get("DIR", ""), loc.get("FILE", ""), col.root_volume)
        if not path or not os.path.exists(path):
            continue
        h = info(path)
        if not h or not h.get("mik"):
            continue
        key, com, cues = wanted(h, cfg)
        inf = e.find("INFO")
        ch = {}
        cur_key = inf.get("KEY") if inf is not None else None
        mk = e.find("MUSICAL_KEY")
        if key and (armonia.to_camelot(cur_key) != key or mk is None or mk.get("VALUE") != str(traktor_key_value(key))):
            ch["key"] = (cur_key, key)
        cur_com = inf.get("COMMENT") if inf is not None else None
        if com and (cur_com or "").strip() != com and comment_is_ours(cur_com):
            ch["comment"] = (cur_com or "", com)
        existing = [c for c in e.findall("CUE_V2") if c.get("HOTCUE", "-1") != "-1"]
        user_hot = [c for c in existing if c.get("TYPE") != "4"]  # TYPE 4 = marcador de grid
        slots = [s for s in range(8) if str(s) not in {c.get("HOTCUE") for c in existing}]
        if cues and not user_hot and slots:
            ch["cues"] = len(cues[:len(slots)])
        if not ch:
            continue
        changes.append({"title": e.get("TITLE"), "path": path, **ch})
        if not apply:
            continue
        if inf is None:
            inf = ET.SubElement(e, "INFO")
        if "key" in ch:
            inf.set("KEY", key)
            if mk is None:
                mk = ET.Element("MUSICAL_KEY")
                first_cue = next((i for i, c in enumerate(list(e)) if c.tag == "CUE_V2"), None)
                e.insert(first_cue, mk) if first_cue is not None else e.append(mk)
            mk.set("VALUE", str(traktor_key_value(key)))
        if "comment" in ch:
            inf.set("COMMENT", com)
        if "cues" in ch:
            for slot, (name, ms) in zip(slots, cues):
                ET.SubElement(e, "CUE_V2", NAME=name or "n.n.", DISPL_ORDER="0", TYPE="0",
                              START=f"{ms:.6f}", LEN="0.000000", REPEATS="-1", HOTCUE=str(slot))
    return changes


def run_traktor(cfg, apply=False, progress=None, backup=True):
    from destinos import traktor as T
    path = T.nml_path(cfg)
    if not path or not Path(path).exists():
        raise T.TraktorError("No encontré collection.nml de Traktor.")
    if apply:
        T._open(cfg)
    col = T.Collection(path)
    changes = plan_traktor(col, cfg, False, progress=progress)
    if not apply or not changes:
        return {"changes": changes, "backup": None}
    bk = T.backup(path) if backup else None
    col = T.Collection(path)
    plan_traktor(col, cfg, True)
    col.save()
    log(f"MIK -> Traktor: {len(changes)} canciones (respaldo {bk})")
    return {"changes": changes, "backup": bk}


# ---------------------------------------------------------------- Serato
def _serato_dbs(cfg):
    from destinos import serato as S
    out = []
    home = S.home_serato(cfg)
    if (home / "database V2").exists():
        out.append(("/" if not S.IS_WIN else S._volume_of(str(home))[0], home))
    if S.IS_MAC and Path("/Volumes").is_dir():
        for v in Path("/Volumes").iterdir():
            d = v / "_Serato_"
            if (d / "database V2").exists() and d != home:
                out.append((str(v), d))
    return out


def plan_serato_db(data, root, cfg, apply=False, info=None):
    """Recorre «database V2»: key (tkey) y comentario (tcom). -> (changes, datos nuevos, sin_cues)."""
    from destinos import serato as S
    info = info or armonia.info
    changes, out, no_cues = [], [], 0
    for tag, d in S.parse(data):
        if tag != "otrk":
            out.append((tag, d))
            continue
        fields = S.parse(d)
        get = {t: v for t, v in fields}
        rel = get.get("pfil", b"").decode("utf-16-be", "replace")
        path = os.path.join(root, rel) if rel else None
        h = info(path) if path and os.path.exists(path) else None
        if not h or not h.get("mik"):
            out.append((tag, d))
            continue
        key, com, cues = wanted(h, cfg)
        if cues and not h.get("serato_cues"):
            no_cues += 1
        cur_key = get.get("tkey", b"").decode("utf-16-be", "replace").strip("\x00") or None
        cur_com = get.get("tcom", b"").decode("utf-16-be", "replace").strip("\x00") or None
        ch = {}
        if key and armonia.to_camelot(cur_key) != key:
            ch["key"] = (cur_key, key)
        if com and (cur_com or "").strip() != com and comment_is_ours(cur_com):
            ch["comment"] = (cur_com or "", com)
        if ch:
            title = get.get("tsng", b"").decode("utf-16-be", "replace").strip("\x00")
            changes.append({"title": title or Path(rel).stem, "path": path, **ch})
            if apply:
                newv = {"tkey": key if "key" in ch else None, "tcom": com if "comment" in ch else None}
                fields = [(t, S._txt(newv[t]) if newv.get(t) else v) for t, v in fields]
                have = {t for t, _ in fields}
                fields += [(t, S._txt(v)) for t, v in newv.items() if v and t not in have]
                d = S.dump(fields)
        out.append((tag, d))
    return changes, S.dump(out), no_cues


def run_serato(cfg, apply=False, progress=None, backup=True):
    from destinos import serato as S
    if not S.available(cfg):
        raise S.SeratoError("No encontré la carpeta de Serato.")
    if apply and S.running():
        raise S.SeratoError("Serato está abierto. Ciérralo para pasarle los datos de Mixed In Key.")
    changes, no_cues, bk = [], 0, None
    for root, sdir in _serato_dbs(cfg):
        if progress:
            progress(f"Revisando Serato ({sdir})…", 0.5)
        f = sdir / "database V2"
        data = f.read_bytes()
        ch, new, nc = plan_serato_db(data, root, cfg, apply)
        changes += ch
        no_cues += nc
        if apply and ch:
            b = S._Backup(sdir)
            S._write(f, new, b)
            bk = "BrainOrder respaldos"
    if apply and changes:
        log(f"MIK -> Serato: {len(changes)} canciones")
    return {"changes": changes, "backup": bk, "serato_no_cues": no_cues}


# ---------------------------------------------------------------- Engine DJ
ENGINE_COLORS = [(0xFF, 0xEA, 0x2C, 0x2C), (0xFF, 0xF8, 0x8F, 0x1E), (0xFF, 0xF8, 0xD9, 0x1E), (0xFF, 0x2C, 0xD2, 0x5A),
                 (0xFF, 0x2C, 0xC5, 0xEA), (0xFF, 0x2C, 0x5A, 0xEA), (0xFF, 0x9B, 0x3B, 0xEA), (0xFF, 0xEA, 0x2C, 0xA8)]


def _qdecomp(b):
    return zlib.decompress(bytes(b)[4:]) if b and len(b) > 4 else None


def _qcomp(raw):
    return len(raw).to_bytes(4, "big") + zlib.compress(raw)


def engine_parse_cues(blob):
    """quickCues -> ([(label, sample_offset, argb)] ×N, resto del blob). None si no se entiende."""
    raw = _qdecomp(blob)
    if not raw or len(raw) < 8:
        return None
    try:
        n = struct.unpack(">q", raw[:8])[0]
        i, cues = 8, []
        for _ in range(n):
            ln = raw[i]
            label = raw[i + 1:i + 1 + ln].decode("utf-8", "replace")
            i += 1 + ln
            off = struct.unpack(">d", raw[i:i + 8])[0]
            argb = tuple(raw[i + 8:i + 12])
            i += 12
            cues.append((label, off, argb))
        return cues, raw[i:]
    except Exception:
        return None


def engine_build_cues(cues, rest):
    raw = struct.pack(">q", len(cues))
    for label, off, argb in cues:
        lb = (label or "").encode("utf-8")[:255]
        raw += bytes([len(lb)]) + lb + struct.pack(">d", off) + bytes(argb)
    return _qcomp(raw + rest)


def engine_sample_rate(track_data, path):
    raw = _qdecomp(track_data)
    if raw and len(raw) >= 8:
        try:
            sr = struct.unpack(">d", raw[:8])[0]
            if 8000 <= sr <= 192000:
                return sr
        except Exception:
            pass
    try:
        import mutagen
        return float(mutagen.File(path).info.sample_rate)
    except Exception:
        return None


def _engine_layout(db):
    """Columnas de Track y dónde están los cues: en Track (Engine 4) o en PerformanceData (Engine 2/3)."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(Track)")}
    perf = {r[1] for r in db.execute("PRAGMA table_info(PerformanceData)")}
    if "quickCues" in cols:
        return cols, "Track"
    if {"trackId", "quickCues"} <= perf:
        return cols, "PerformanceData"
    return cols, None


def plan_engine(db, lib_dir, cfg, apply=False, info=None, progress=None):
    info = info or armonia.info
    cols, where = _engine_layout(db)
    if "path" not in cols:
        return []
    sel = ["t.id", "t.path"] + [f"t.{c}" for c in ("title", "key", "comment") if c in cols]
    names = ["id", "path"] + [c for c in ("title", "key", "comment") if c in cols]
    join = ""
    if where == "Track":
        sel += ["t.quickCues", "t.trackData" if "trackData" in cols else "NULL"]
    elif where == "PerformanceData":
        sel += ["p.quickCues", "p.trackData"]
        join = " LEFT JOIN PerformanceData p ON p.trackId = t.id"
    if where:
        names += ["quickCues", "trackData"]
    rows = db.execute(f"SELECT {', '.join(sel)} FROM Track t{join}").fetchall()
    changes = []
    for n, row in enumerate(rows, 1):
        if progress and n % 300 == 0:
            progress(f"Revisando Engine DJ {n}/{len(rows)}…", n / len(rows))
        r = dict(zip(names, row))
        if not r.get("path"):
            continue
        path = os.path.normpath(os.path.join(lib_dir, r["path"]))
        if not os.path.exists(path):
            continue
        h = info(path)
        if not h or not h.get("mik"):
            continue
        key, com, cues = wanted(h, cfg)
        ch, sets, qc = {}, {}, None
        if key and "key" in r and r["key"] != engine_key_value(key):
            ch["key"] = (r["key"], key)
            sets["key"] = engine_key_value(key)
        if com and "comment" in r and (r["comment"] or "").strip() != com and comment_is_ours(r["comment"]):
            ch["comment"] = (r["comment"] or "", com)
            sets["comment"] = com
        if cues and r.get("quickCues"):  # solo pistas ya analizadas por Engine
            parsed = engine_parse_cues(r["quickCues"])
            if parsed and all(off < 0 for _, off, _ in parsed[0]):
                sr = engine_sample_rate(r.get("trackData"), path)
                if sr:
                    slots = list(parsed[0]) + [("", -1.0, (0, 0, 0, 0))] * max(0, 8 - len(parsed[0]))
                    for i, (name, ms) in enumerate(cues[:8]):
                        slots[i] = (name, ms * sr / 1000.0, ENGINE_COLORS[i])
                    qc = engine_build_cues(slots, parsed[1])
                    ch["cues"] = min(8, len(cues))
        if not ch:
            continue
        changes.append({"title": r.get("title") or Path(path).stem, "path": path, **ch})
        if apply:
            if sets:
                q = ", ".join(f"{k} = ?" for k in sets)
                db.execute(f"UPDATE Track SET {q} WHERE id = ?", (*sets.values(), r["id"]))
            if qc is not None:
                tbl, idc = ("Track", "id") if where == "Track" else ("PerformanceData", "trackId")
                db.execute(f"UPDATE {tbl} SET quickCues = ? WHERE {idc} = ?", (qc, r["id"]))
    return changes


def run_engine(cfg, apply=False, progress=None, backup=True):
    import sqlite3
    from destinos import engine as E
    if not E.available(cfg):
        raise E.EngineError("No encontré la librería de Engine DJ.")
    lib_dir = str(E.library_dir(cfg))
    if not apply:
        src = sqlite3.connect(f"file:{E.db_path(cfg)}?mode=ro", uri=True)
        db = sqlite3.connect(":memory:")
        try:
            src.backup(db)
        finally:
            src.close()
        try:
            return {"changes": plan_engine(db, lib_dir, cfg, False, progress=progress), "backup": None}
        finally:
            db.close()
    E._open(cfg)
    db = sqlite3.connect(E.db_path(cfg), timeout=10)
    try:
        changes = plan_engine(db, lib_dir, cfg, False, progress=progress)
        if not changes:
            return {"changes": [], "backup": None}
        db.close()
        bk = E.backup(cfg) if backup else None
        db = sqlite3.connect(E.db_path(cfg), timeout=10)
        with db:
            plan_engine(db, lib_dir, cfg, True)
        log(f"MIK -> Engine DJ: {len(changes)} canciones (respaldo {bk})")
        return {"changes": changes, "backup": bk}
    except sqlite3.Error as e:
        raise E.EngineError(f"No pude pasar los datos de MIK a Engine DJ (no se guardó nada): {e}")
    finally:
        db.close()


# ---------------------------------------------------------------- todos
RUNNERS = {"rekordbox": run_rekordbox, "traktor": run_traktor, "serato": run_serato, "engine": run_engine}


def run(cfg, key, apply=False, progress=None, backup=True):
    """backup=False: cuando la misma operación ya respaldó la librería de ese programa (Organizar)."""
    res = RUNNERS[key](cfg, apply=apply, progress=progress, backup=backup)
    if apply and res.get("changes"):
        armonia.save()
    return res


def summary(changes):
    return {"count": len(changes), "keys": sum(1 for c in changes if "key" in c),
            "comments": sum(1 for c in changes if "comment" in c),
            "cues": sum(1 for c in changes if c.get("cues")), "sample": changes[:30]}
