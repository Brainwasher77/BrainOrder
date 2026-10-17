"""Key (Camelot), energía y BPM de cada archivo — lo que dejó Mixed In Key (10 u 11) u otro programa.

Orden de confianza (se usa lo primero que aparezca):
  1. Campos propios de Mixed In Key (JSON): GEOB «Key» / «Energy» en MP3/AIFF/WAV,
     «----:com.mixedinkey.mixedinkey:key/energy» en M4A, «key»/«energy» (base64) en FLAC.
  2. Campos estándar: Initial Key (TKEY / initialkey / key), EnergyLevel.
  3. Comentario «8A - Energy 6» y grouping «Energy 6».
Cualquier notación de tonalidad (Camelot 8A, Open Key 1m, musical «Am», «C#m», «Eb major») se pasa a Camelot.
Solo lee: nunca modifica los archivos. Se guarda en caché por ruta + tamaño + fecha.
"""
import base64
import json
import os
import re
import threading
from pathlib import Path

try:
    import mutagen
except Exception:  # pragma: no cover
    mutagen = None

_CACHE = {}
_FILE = [None]
_DIRTY = [False]
_LOCK = threading.Lock()
VERSION = 1  # subir si cambia la lógica, para releer

# ---------------------------------------------------------------- notación
_NOTES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "FB": 4, "E#": 5, "F": 5, "F#": 6, "GB": 6,
          "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11, "B#": 0}
# semitono -> número Camelot (mayor = B, menor = A)
_MAJOR = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}
_MINOR = {9: 8, 4: 9, 11: 10, 6: 11, 1: 12, 8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7}


def to_camelot(s):
    """'8a' / '08A' / '1m' (Open Key) / 'Am' / 'C#m' / 'Eb major' / 'F#min' -> '8A'. None si no se entiende."""
    if not s:
        return None
    t = str(s).strip().replace("♯", "#").replace("♭", "b")
    m = re.fullmatch(r"0?(1[0-2]|[1-9])\s*([ABab])", t)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"
    m = re.fullmatch(r"0?(1[0-2]|[1-9])\s*([dmDM])", t)  # Open Key: 1d = C mayor = 8B, 1m = Am = 8A
    if m:
        n = (int(m.group(1)) + 6) % 12 + 1
        return f"{n}{'B' if m.group(2).lower() == 'd' else 'A'}"
    m = re.fullmatch(r"([A-Ga-g])\s*([#b]?)\s*(minor|major|min|maj|moll|dur|m|M)?\.?", t, flags=0)
    if m:
        note = m.group(1).upper() + m.group(2).upper()
        q = m.group(3) or ""
        minor = q in ("m", "min", "minor", "moll")
        semi = _NOTES.get(note)
        if semi is None:
            return None
        return f"{(_MINOR if minor else _MAJOR)[semi]}{'A' if minor else 'B'}"
    return None


def camelot_sort(k):
    """Orden de la rueda: 1A, 1B, 2A, 2B… (sin key al final)."""
    m = re.fullmatch(r"(\d+)([AB])", k or "")
    return (int(m.group(1)), m.group(2)) if m else (99, "Z")


def compatible(a, b):
    """Mezcla armónica: misma key, ±1 en la rueda (misma letra) o cambio A/B con el mismo número."""
    if not a or not b:
        return False
    na, la = int(a[:-1]), a[-1]
    nb, lb = int(b[:-1]), b[-1]
    if la == lb:
        return (na - nb) % 12 in (0, 1, 11)
    return na == nb


# ---------------------------------------------------------------- lectura
def _json_b64(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if isinstance(v, (bytes, bytearray)):
        raw = bytes(v)
    else:
        raw = str(v).encode("utf-8", "ignore")
    for cand in (raw, b"".join(raw.split())):
        try:
            return json.loads(cand.decode("utf-8"))
        except Exception:
            pass
        try:
            return json.loads(base64.b64decode(cand + b"=" * (-len(cand) % 4)).decode("utf-8"))
        except Exception:
            pass
    return None


def _first(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if hasattr(v, "text"):
        v = v.text[0] if v.text else None
    if isinstance(v, (bytes, bytearray)):
        v = bytes(v).decode("utf-8", "ignore")
    return None if v is None else str(v).strip()


_COMMENT = re.compile(r"\b(0?(?:1[0-2]|[1-9])[AB])\b(?:.*?Energy\s*(\d{1,2}))?", re.I)
_ENERGY = re.compile(r"Energy\s*(\d{1,2})", re.I)


def _energy(v):
    try:
        n = int(float(str(v).strip()))
        return n if 1 <= n <= 10 else None
    except Exception:
        m = _ENERGY.search(str(v or ""))
        return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 10 else None


def _bpm(v):
    try:
        b = float(str(v).replace(",", ".").strip())
        return round(b, 1) if 40 <= b <= 250 else None
    except Exception:
        return None


def read_tags(path):
    """-> {'key','energy','bpm','mik'} sin caché."""
    out = {"key": None, "energy": None, "bpm": None, "mik": False}
    if not mutagen:
        return out
    try:
        f = mutagen.File(path)
    except Exception:
        return out
    if f is None or f.tags is None:
        return out
    t = f.tags
    ext = Path(path).suffix.lower()
    mik_key = mik_energy = None
    std_key = std_energy = bpm = None
    comments, groupings = [], []
    try:
        if ext in (".mp3", ".aif", ".aiff", ".wav") or hasattr(t, "getall"):
            for frame in t.getall("GEOB"):
                d = getattr(frame, "desc", "")
                if d == "Key":
                    j = _json_b64(frame.data) or {}
                    mik_key = j.get("key")
                elif d == "Energy":
                    j = _json_b64(frame.data) or {}
                    mik_energy = j.get("energyLevel")
            k = t.getall("TKEY")
            std_key = _first(k[0]) if k else None
            for fr in t.getall("TXXX"):
                if fr.desc.lower() in ("energylevel", "energy"):
                    std_energy = _first(fr)
                elif fr.desc.lower() in ("initialkey", "initial key") and not std_key:
                    std_key = _first(fr)
            b = t.getall("TBPM")
            bpm = _first(b[0]) if b else None
            comments = [_first(c) for c in t.getall("COMM")]
            groupings = [_first(g) for g in t.getall("TIT1")]
        elif ext in (".m4a", ".mp4", ".aac", ".alac"):
            mik_key = (_json_b64(t.get("----:com.mixedinkey.mixedinkey:key")) or {}).get("key")
            mik_energy = (_json_b64(t.get("----:com.mixedinkey.mixedinkey:energy")) or {}).get("energyLevel")
            std_key = _first(t.get("----:com.apple.iTunes:initialkey"))
            std_energy = _first(t.get("----:com.apple.iTunes:energylevel"))
            tm = t.get("tmpo")
            bpm = tm[0] if tm else None
            comments = [_first(t.get("©cmt"))]
            groupings = [_first(t.get("©grp"))]
        else:  # FLAC / OGG (comentarios Vorbis)
            low = {k.lower(): v for k, v in t.items()} if hasattr(t, "items") else {}
            j = _json_b64(low.get("key"))
            mik_key = j.get("key") if isinstance(j, dict) else None
            j = _json_b64(low.get("energy"))
            mik_energy = j.get("energyLevel") if isinstance(j, dict) else None
            std_key = _first(low.get("initialkey")) or (_first(low.get("key")) if not mik_key else None)
            std_energy = _first(low.get("energylevel"))
            bpm = _first(low.get("bpm"))
            comments = [_first(low.get("comment")), _first(low.get("description"))]
            groupings = [_first(low.get("grouping"))]
    except Exception:
        pass
    key = to_camelot(mik_key)
    out["mik"] = bool(key)
    if not key:
        key = to_camelot(std_key)
    energy = _energy(mik_energy) if mik_energy is not None else None
    if energy:
        out["mik"] = True
    if energy is None and std_energy:
        energy = _energy(std_energy)
    for c in comments:
        if not c:
            continue
        m = _COMMENT.search(c)
        if m:
            key = key or to_camelot(m.group(1))
            if energy is None and m.group(2):
                energy = _energy(m.group(2))
        if energy is None and _ENERGY.search(c):
            energy = _energy(c)
    for g in groupings:
        if energy is None and g:
            energy = _energy(g)
    out.update(key=key, energy=energy, bpm=_bpm(bpm))
    return out


# ---------------------------------------------------------------- caché
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
            tmp = _FILE[0].with_name(f".{_FILE[0].name}.tmp")
            tmp.write_text(json.dumps({"v": VERSION, "files": dict(_CACHE)}), "utf-8")
            os.replace(tmp, _FILE[0])
            _DIRTY[0] = False
        except Exception:
            pass


def info(path):
    """Key/energía/BPM con caché (se relee solo si el archivo cambió, p. ej. después de pasar por MIK)."""
    try:
        st = os.stat(path)
    except OSError:
        return {"key": None, "energy": None, "bpm": None, "mik": False}
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    c = _CACHE.get(path)
    if c and c.get("s") == stamp:
        return c["d"]
    d = read_tags(path)
    _CACHE[path] = {"s": stamp, "d": d}
    _DIRTY[0] = True
    return d
