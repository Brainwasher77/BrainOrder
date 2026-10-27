"""Etiquetas de las canciones (artista, título, género, álbum): leer con caché, encontrar las que tienen datos
incompletos, proponer cómo completarlas y escribirlas.

- Leer: mutagen «fácil» (MP3, M4A, FLAC, OGG, AIFF/WAV con ID3). Caché por ruta + tamaño + fecha
  (SUPPORT/etiquetas.json): en tu biblioteca entera solo se lee lo que cambió.
- Incompletas: artista vacío o «Desconocido / Unknown Artist…», título vacío, nombre de archivo sin
  «Artista - Título» (así BrainOrder no puede reconocer la canción) o sin género.
- Propuesta (de más a menos segura): la canción de Spotify con la que BrainOrder ya cruzó el archivo; el título
  que trae «Artista - Título» adentro; el nombre del archivo. Se limpia basura típica de descargas
  («(WWW.ELGENERO.COM)», «on iTunes», «- from YouTube», «(1)»…).
- Escribir: solo lo que eliges; se guarda cómo estaba para poder deshacer.
"""
import json
import os
import re
import threading
from pathlib import Path

VERSION = 1
FIELDS = ("artist", "title", "genre", "album")
BAD_ARTISTS = {"", "desconocido", "unknown", "unknown artist", "artista desconocido", "unknown mobile", "<unknown>",
               "[unknown]", "sin artista", "no artist", "artist", "track", "various", "n/a", "na", "none", "null",
               "unknown artist(s)", "artista", "interprete desconocido", "intérprete desconocido"}
BAD_TITLES = {"", "track", "untitled", "sin titulo", "sin título", "unknown", "desconocido", "audio", "pista"}

_CACHE, _FILE, _DIRTY, _LOCK = {}, [None], [False], threading.Lock()


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
            _FILE[0].parent.mkdir(parents=True, exist_ok=True)
            tmp = _FILE[0].with_name(f".{_FILE[0].name}.tmp")
            tmp.write_text(json.dumps({"v": VERSION, "files": dict(_CACHE)}, ensure_ascii=False), "utf-8")
            os.replace(tmp, _FILE[0])
            _DIRTY[0] = False
        except Exception:
            pass


def _easy(path):
    import mutagen
    f = mutagen.File(path, easy=True)
    if f is None:
        return None
    if f.tags is None and path.lower().endswith((".aif", ".aiff", ".wav")):
        f = mutagen.File(path)  # AIFF/WAV: ID3 «crudo»
    return f


def _is_raw_id3(tags):
    """ID3 «crudo» (AIFF/WAV, o MP3 abierto sin modo fácil): se escribe por marcos (TPE1, TIT2…)."""
    from mutagen.id3 import ID3
    return isinstance(tags, ID3)


def _raw_get(f, field):
    """AIFF/WAV con ID3 sin modo fácil."""
    frame = {"artist": "TPE1", "title": "TIT2", "genre": "TCON", "album": "TALB"}[field]
    t = getattr(f, "tags", None)
    if t is None or not hasattr(t, "getall"):
        return ""
    fr = t.getall(frame)
    return str(fr[0].text[0]) if fr and fr[0].text else ""


def read_raw(path):
    out = {k: "" for k in FIELDS}
    try:
        f = _easy(path)
    except Exception:
        return out
    if f is None or f.tags is None:
        return out
    raw = _is_raw_id3(f.tags)
    for k in FIELDS:
        try:
            if raw:
                out[k] = _raw_get(f, k)
            else:
                v = f.tags.get(k)
                out[k] = (" / ".join(str(x) for x in v) if isinstance(v, list) else str(v or "")).strip()
        except Exception:
            out[k] = ""
    return out


def read(path):
    """{artist, title, genre, album} con caché (se relee solo si el archivo cambió)."""
    try:
        st = os.stat(path)
    except OSError:
        return {k: "" for k in FIELDS}
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    c = _CACHE.get(path)
    if c and c.get("s") == stamp:
        return c["d"]
    d = read_raw(path)
    with _LOCK:
        _CACHE[path] = {"s": stamp, "d": d}
        _DIRTY[0] = True
    return d


def write(path, values):
    """Escribe en el archivo solo los campos que vienen en values. -> lo que había antes (para deshacer)."""
    old = read_raw(path)
    f = _easy(path)
    if f is None:
        raise ValueError("formato sin etiquetas")
    if f.tags is None:
        f.add_tags()
    if not _is_raw_id3(f.tags):
        for k, v in values.items():
            if k not in FIELDS:
                continue
            if v:
                f.tags[k] = [v]
            elif k in f.tags:
                del f.tags[k]
    else:
        from mutagen.id3 import TPE1, TIT2, TCON, TALB
        cls = {"artist": TPE1, "title": TIT2, "genre": TCON, "album": TALB}
        for k, v in values.items():
            if k not in cls:
                continue
            frame = cls[k].__name__
            f.tags.delall(frame)
            if v:
                f.tags.add(cls[k](encoding=3, text=[v]))
    # ID3 2.3 se guarda como 2.3 (así lo dejan Mixed In Key y varios programas de DJ; no se cambia de versión)
    id3 = f.tags if _is_raw_id3(f.tags) else getattr(f.tags, "_EasyID3__id3", None)
    if id3 is not None and tuple(getattr(id3, "version", (2, 4, 0)))[:2] == (2, 3):
        f.save(v2_version=3)
    else:
        f.save()
    with _LOCK:
        _CACHE.pop(path, None)
        _DIRTY[0] = True
    return {k: old.get(k, "") for k in values if k in FIELDS}


# ---------------------------------------------------------------- incompletas y propuestas
_JUNK = [
    r"\(?\s*www\.[^\s)\]]+\s*\)?", r"\[?\s*www\.[^\s\]]+\s*\]?",
    r"\s*-?\s*from\s+youtube\b", r"\s+on\s+itunes\b", r"\s*\((official\s+)?(music\s+)?(video|audio|lyric[s]?|lyric video|visualizer|videoclip|video oficial|audio oficial)\)",
    r"\s*\[(official\s+)?(music\s+)?(video|audio|lyric[s]?|visualizer)\]", r"\s*\(\s*\d\s*\)\s*$", r"\s*\(\d{4}\)\s*$",
    r"\s*\b(hq|hd|320\s*kbps|128\s*kbps)\b", r"\s*\[\s*\]|\(\s*\)",
]


def clean(s):
    s = str(s or "")
    for rx in _JUNK:
        s = re.sub(rx, "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" -_.·")
    return s


def bad_artist(a):
    return clean(a).strip().lower() in BAD_ARTISTS


def bad_title(t):
    return clean(t).strip().lower() in BAD_TITLES


def _split(s):
    """«Artista - Título» -> (artista, título) o None."""
    s = clean(s)
    if " - " not in s:
        return None
    a, t = s.split(" - ", 1)
    a, t = a.strip(), t.strip()
    if not a or not t or bad_artist(a) or re.fullmatch(r"\d{1,3}", a):
        return None
    return a, t


def safe_filename(artist, title, ext):
    name = f"{artist} - {title}" if artist else title
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:180] or "Sin título") + ext


def check(path, tags, spotify=None):
    """Problemas y propuesta para una canción.
    spotify: {artists, name} de la canción de Spotify con la que ya se cruzó este archivo (o None).
    -> None si está completa, o {problems: [...], prop: {artist, title}, why, newname}"""
    p = Path(path)
    stem = re.sub(r"\s*\(\d+\)$", "", p.stem)
    ta, tt, tg = tags.get("artist", ""), tags.get("title", ""), tags.get("genre", "")
    problems = []
    if bad_artist(ta):
        problems.append("artista")
    if bad_title(tt):
        problems.append("título")
    fn = _split(stem)
    fn_artist_bad = " - " in stem and bad_artist(stem.split(" - ", 1)[0])
    if fn is None:
        problems.append("nombre")
    if not tg.strip():
        problems.append("género")
    if not problems:
        return None
    prop, why = None, None
    if spotify and spotify.get("name") and spotify.get("artists"):
        # Spotify solo completa lo que falta: si el título ya está bien (p. ej. «… (K&F Edit)») se conserva
        sp_title = spotify["name"] if bad_title(tt) else (_split(tt)[1] if bad_artist(ta) and _split(tt) else tt)
        prop, why = (", ".join(spotify["artists"]), sp_title), "de Spotify"
    if prop is None and bad_artist(ta) and _split(tt):
        prop, why = _split(tt), "del título"
    if prop is None and fn is not None and not fn_artist_bad:
        prop, why = fn, "del nombre del archivo"
    if prop is None and fn_artist_bad and _split(stem.split(" - ", 1)[1]):
        prop, why = _split(stem.split(" - ", 1)[1]), "del nombre del archivo"
    if prop is None and not bad_artist(ta) and not bad_title(tt):
        prop, why = (clean(ta), clean(tt)), "de sus etiquetas"
    out = {"problems": problems, "prop": None, "why": None, "newname": None}
    if prop:
        a, t = clean(prop[0]), clean(prop[1])
        out["prop"] = {"artist": a, "title": t}
        out["why"] = why
        new = safe_filename(a, t, p.suffix)
        # el archivo solo se renombra si su nombre no sirve (sin «Artista - Título» o con artista desconocido)
        if new != p.name and ("nombre" in problems or fn_artist_bad):
            out["newname"] = new
    only_genre = problems == ["género"]
    if only_genre:
        out["prop"] = None
        out["newname"] = None
    return out
