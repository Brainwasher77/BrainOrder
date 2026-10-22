"""Key (Camelot), energía y BPM de cada archivo — lo que dejó Mixed In Key (10 u 11) u otro programa.

Mixed In Key SIEMPRE tiene prioridad sobre cualquier otro programa:
  1. Campos propios de MIK (JSON): GEOB «Key» / «Energy» / «BeatGrid» en MP3/AIFF/WAV,
     «----:com.mixedinkey.mixedinkey:…» en M4A, «key»/«energy»/«beatgrid» (base64) en FLAC.
  2. Textos con el formato de MIK: comentario «8A - Energy 6», EnergyLevel, grouping «Energy 6».
  3. Solo si no hay nada de MIK: Initial Key / TKEY, BPM estándar, comentario con solo la key.
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
VERSION = 4  # subir si cambia la lógica, para releer

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


def _mik(j, field):
    """Valor de un JSON de Mixed In Key (solo si de verdad viene de MIK)."""
    if not isinstance(j, dict):
        return None
    if j.get("source") not in (None, "mixedinkey"):
        return None
    return j.get(field)


def _cues(j):
    """CuePoints de MIK -> [[nombre, ms], …] (máx. 8, en orden de tiempo)."""
    if not isinstance(j, dict) or j.get("source") not in (None, "mixedinkey"):
        return []
    out = []
    for c in j.get("cues") or []:
        try:
            t = float(c.get("time"))
        except Exception:
            continue
        if t >= 0:
            out.append([str(c.get("name") or "")[:40], round(t, 3)])
    out.sort(key=lambda x: x[1])
    return out[:8]


def _serato_has_cues(raw, depth=0):
    """¿Los marcadores de Serato (Markers2) del archivo traen hot cues?"""
    if raw is None or depth > 3:
        return False
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if hasattr(raw, "text"):
        raw = raw.text[0] if raw.text else None
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "ignore")
    raw = bytes(raw or b"")
    if b"CUE\x00" in raw:
        return True
    i = raw.find(b"Serato Markers2\x00")
    if i >= 0:
        raw = raw[i + 16:]
    if raw[:2] == b"\x01\x01":
        raw = raw[2:]
    b64 = b"".join(raw.split(b"\x00")[0].split())
    try:
        dec = base64.b64decode(b64 + b"=" * (-len(b64) % 4))
    except Exception:
        return False
    return bool(dec) and dec != raw and _serato_has_cues(dec, depth + 1)


def read_tags(path):
    """-> {'key','energy','bpm','mik','key_mik','cues','serato_cues'} sin caché.

    Prioridad SIEMPRE para Mixed In Key:
      1. JSON propio de MIK (Key, Energy, BeatGrid→tempo).
      2. Formatos de texto que escribe MIK: comentario «8A - Energy 6», EnergyLevel, grouping «Energy 6».
      3. Recién ahí, lo de otros programas: Initial Key / TKEY, BPM estándar, comentario con solo la key.
    """
    out = {"key": None, "energy": None, "bpm": None, "mik": False, "key_mik": False, "cues": [], "serato_cues": False}
    if not mutagen:
        return out
    try:
        f = mutagen.File(path)
        t = f.tags if f is not None else None
    except Exception:
        t = None
    if t is None and str(path).lower().endswith((".mp3", ".aif", ".aiff", ".wav")):
        try:  # el audio no se pudo leer (archivo dañado o raro), pero las etiquetas sí
            from mutagen.id3 import ID3
            t = ID3(path)
        except Exception:
            t = None
    if t is None:
        return out
    ext = Path(path).suffix.lower()
    mik_key = mik_energy = mik_bpm = None
    std_key = mik_energy_txt = std_bpm = None
    comments, groupings = [], []
    cues, serato = [], False
    try:
        if hasattr(t, "getall"):  # ID3: MP3, AIFF, WAV
            for frame in t.getall("GEOB"):
                d = getattr(frame, "desc", "")
                if d == "Key":
                    mik_key = _mik(_json_b64(frame.data), "key")
                elif d == "Energy":
                    mik_energy = _mik(_json_b64(frame.data), "energyLevel")
                elif d == "BeatGrid":
                    mik_bpm = _mik(_json_b64(frame.data), "tempo")
                elif d == "CuePoints":
                    cues = _cues(_json_b64(frame.data))
                elif d == "Serato Markers2":
                    serato = serato or _serato_has_cues(frame.data)
            k = t.getall("TKEY")
            std_key = _first(k[0]) if k else None
            for fr in t.getall("TXXX"):
                if fr.desc.lower() in ("energylevel", "energy"):
                    mik_energy_txt = _first(fr)
                elif fr.desc.lower() in ("initialkey", "initial key") and not std_key:
                    std_key = _first(fr)
            b = t.getall("TBPM")
            std_bpm = _first(b[0]) if b else None
            comments = [_first(c) for c in t.getall("COMM")]
            groupings = [_first(g) for g in t.getall("TIT1")]
        elif ext in (".m4a", ".mp4", ".aac", ".alac"):
            mik_key = _mik(_json_b64(t.get("----:com.mixedinkey.mixedinkey:key")), "key")
            mik_energy = _mik(_json_b64(t.get("----:com.mixedinkey.mixedinkey:energy")), "energyLevel")
            mik_bpm = _mik(_json_b64(t.get("----:com.mixedinkey.mixedinkey:beatgrid")), "tempo")
            cues = _cues(_json_b64(t.get("----:com.mixedinkey.mixedinkey:cuepoints")))
            serato = _serato_has_cues(t.get("----:com.serato.dj:markersv2"))
            std_key = _first(t.get("----:com.apple.iTunes:initialkey"))
            mik_energy_txt = _first(t.get("----:com.apple.iTunes:energylevel"))
            tm = t.get("tmpo")
            std_bpm = tm[0] if tm else None
            comments = [_first(t.get("©cmt"))]
            groupings = [_first(t.get("©grp"))]
        else:  # FLAC / OGG (comentarios Vorbis)
            low = {k.lower(): v for k, v in t.items()} if hasattr(t, "items") else {}
            mik_key = _mik(_json_b64(low.get("key")), "key")
            mik_energy = _mik(_json_b64(low.get("energy")), "energyLevel")
            mik_bpm = _mik(_json_b64(low.get("beatgrid")), "tempo")
            cues = _cues(_json_b64(low.get("cuepoints")))
            serato = _serato_has_cues(low.get("serato_markers_v2"))
            std_key = _first(low.get("initialkey")) or (_first(low.get("key")) if not mik_key else None)
            mik_energy_txt = _first(low.get("energylevel"))
            std_bpm = _first(low.get("bpm"))
            comments = [_first(low.get("comment")), _first(low.get("description"))]
            groupings = [_first(low.get("grouping"))]
    except Exception:
        pass

    # textos con el formato de MIK: «8A - Energy 6» (comentario) y «Energy 6» (grouping)
    mik_txt_key = mik_txt_energy = bare_key = None
    for c in comments:
        if not c:
            continue
        m = _COMMENT.search(c)
        if m and m.group(2):
            mik_txt_key = mik_txt_key or to_camelot(m.group(1))
            mik_txt_energy = mik_txt_energy or _energy(m.group(2))
        elif m:
            bare_key = bare_key or to_camelot(m.group(1))
        if mik_txt_energy is None and _ENERGY.search(c):
            mik_txt_energy = _energy(c)
    group_energy = next((_energy(g) for g in groupings if g and _energy(g)), None)

    # KEY: MIK (JSON) > MIK (comentario «8A - Energy») > otros programas
    key_mik = to_camelot(mik_key) or mik_txt_key
    key = key_mik or to_camelot(std_key) or bare_key
    # ENERGÍA: solo la escribe MIK; el JSON manda
    energy = (_energy(mik_energy) if mik_energy is not None else None) or _energy(mik_energy_txt) \
        or mik_txt_energy or group_energy
    # BPM: el de MIK (BeatGrid) manda sobre el estándar
    bpm = _bpm(mik_bpm) or _bpm(std_bpm)
    # «analizada con MIK» = cualquier dato salió de MIK (la energía solo la escribe MIK)
    out.update(key=key, energy=energy, bpm=bpm, mik=bool(key_mik or energy or _bpm(mik_bpm)),
               key_mik=bool(key_mik), cues=cues, serato_cues=bool(serato))
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
        return {"key": None, "energy": None, "bpm": None, "mik": False, "cues": []}
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    c = _CACHE.get(path)
    if c and c.get("s") == stamp:
        return c["d"]
    d = read_tags(path)
    _CACHE[path] = {"s": stamp, "d": d}
    _DIRTY[0] = True
    return d
