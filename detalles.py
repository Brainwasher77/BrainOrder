"""Detalles de cada archivo para las columnas de la lista de canciones (como en Apple Music / iTunes):
género, año, álbum, número de pista, compositor, comentario, bitrate, frecuencia, tamaño, formato,
duración y la fecha en que llegó al computador. Solo lee etiquetas (nunca escribe). Caché por ruta +
tamaño + fecha en SUPPORT/detalles.json: la primera vez tarda un poco con playlists grandes, después es al
instante."""
import json
import os
import re
import threading
from pathlib import Path

VERSION = 1
_CACHE, _FILE, _DIRTY, _LOCK = {}, [None], [False], threading.Lock()


def load(path):
    _FILE[0] = Path(path)
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        if data.get("v") == VERSION:
            _CACHE.update(data.get("files") or {})
    except Exception:
        pass


def save():
    if not (_FILE[0] and _DIRTY[0]):
        return
    with _LOCK:
        try:
            _FILE[0].parent.mkdir(parents=True, exist_ok=True)
            tmp = _FILE[0].with_name(f".{_FILE[0].name}.tmp")
            tmp.write_text(json.dumps({"v": VERSION, "files": dict(_CACHE)}, ensure_ascii=False), "utf-8")
            os.replace(tmp, _FILE[0])
            _DIRTY[0] = False
        except Exception:
            pass


def _first(v):
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "").strip()


def _year(s):
    m = re.search(r"(1[89]\d\d|20\d\d)", s or "")
    return int(m.group(1)) if m else None


def _num(s):
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else None


_RAW = {"genre": "TCON", "date": "TDRC", "year": "TYER", "album": "TALB", "tracknumber": "TRCK",
        "composer": "TCOM", "albumartist": "TPE2"}


def read_raw(path):
    out = {"genre": "", "year": None, "album": "", "track": None, "composer": "", "albumartist": "",
           "comment": "", "bitrate": None, "sr": None, "secs": None}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None and f.tags is None and path.lower().endswith((".aif", ".aiff", ".wav")):
            f = mutagen.File(path)
    except Exception:
        f = None
    if f is None:  # audio que mutagen no reconoce: al menos las etiquetas ID3 si tiene
        try:
            from mutagen.id3 import ID3

            class _F:
                info = None
                tags = ID3(path)
            f = _F()
        except Exception:
            return out
    info = getattr(f, "info", None)
    if info is not None:
        br = getattr(info, "bitrate", None)
        out["bitrate"] = int(round(br / 1000)) if br else None
        out["sr"] = getattr(info, "sample_rate", None) or None
        ln = getattr(info, "length", None)
        out["secs"] = round(float(ln), 1) if ln else None
    t = f.tags
    if t is None:
        return out
    try:
        from mutagen.id3 import ID3
        raw = isinstance(t, ID3)
    except Exception:
        raw = False
    if raw:
        def g(k):
            fr = t.getall(_RAW[k]) if k in _RAW else []
            return str(fr[0].text[0]) if fr and getattr(fr[0], "text", None) else ""
        com = t.getall("COMM")
        out["comment"] = str(com[0].text[0]) if com and com[0].text else ""
    else:
        def g(k):
            try:
                return _first(t.get(k))
            except Exception:
                return ""
        try:
            out["comment"] = _first(t.get("comment"))
        except Exception:
            pass
    out["genre"] = g("genre")
    out["year"] = _year(g("date") or (g("year") if raw else ""))
    out["album"] = g("album")
    out["track"] = _num(g("tracknumber"))
    out["composer"] = g("composer")
    out["albumartist"] = g("albumartist")
    out["comment"] = (out["comment"] or "")[:200]
    return out


def info(path):
    """{genre, year, album, track, composer, albumartist, comment, bitrate, sr, secs, size, added, ext}"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    c = _CACHE.get(path)
    if not (c and c.get("s") == stamp):
        d = read_raw(path)
        with _LOCK:
            _CACHE[path] = c = {"s": stamp, "d": d}
            _DIRTY[0] = True
    # «Agregada»: cuándo llegó el archivo a tu computador (en Mac la fecha de creación; si no, la de modificación)
    added = getattr(st, "st_birthtime", None) or st.st_mtime
    return {**c["d"], "size": st.st_size, "added": int(min(added, st.st_mtime)),
            "ext": Path(path).suffix.lower().lstrip(".")}


def many(paths, progress=None):
    out = {}
    paths = [p for p in dict.fromkeys(paths) if p]
    for n, p in enumerate(paths, 1):
        if progress and n % 100 == 0:
            progress(f"Leyendo datos de las canciones: {n}/{len(paths)}…", n / len(paths))
        d = info(p)
        if d:
            out[p] = d
    save()
    return out
