"""Buscar en internet los datos que le faltan a una canción (artista, título, género).

Fuentes gratis y sin cuenta, en este orden:
  1. Deezer (api.deezer.com): artista, título, álbum y el género del álbum. Es la misma fuente de la que vienen
     los géneros que ya tienen tus descargas («Electro», «Rap/Hip Hop», «Latino»…), así que quedan parejos.
  2. iTunes / Apple Music (itunes.apple.com/search): si Deezer no la tiene o no trae género.
No gasta consultas de Spotify (para eso está el 🔎 de cada canción).

Cada resultado se compara con tu archivo: la DURACIÓN (si dura lo mismo es casi seguro la misma grabación) y
cuánto se parecen artista + título a lo que dice el nombre del archivo. Solo se da por «segura» la que dura
igual (±3 s) y se parece; las demás quedan como «posibles» para que elijas tú.
Los resultados se guardan (SUPPORT/busqueda_datos.json): no se vuelve a buscar lo mismo.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import deezer
import etiquetas
from biblioteca import norm, duration

TOL = 3.0            # segundos de diferencia para decir «dura igual»
NONE_DAYS = 14       # lo que no se encontró se vuelve a buscar después de esto
_ITUNES_GAP = 3.2    # Apple deja ~20 consultas por minuto
_it_last = [0.0]
_it_lock = threading.Lock()
_CACHE, _FILE, _LOCK = {}, [None], threading.Lock()
_ALBUM_GENRE = {}


# ---------------------------------------------------------------- caché
def load(path):
    _FILE[0] = Path(path)
    try:
        d = json.loads(Path(path).read_text("utf-8"))
        _CACHE.update(d.get("files") or {})
        _ALBUM_GENRE.update(d.get("albums") or {})
    except Exception:
        pass


def save():
    if not _FILE[0]:
        return
    with _LOCK:
        try:
            _FILE[0].parent.mkdir(parents=True, exist_ok=True)
            tmp = _FILE[0].with_name(f".{_FILE[0].name}.tmp")
            tmp.write_text(json.dumps({"files": _CACHE, "albums": _ALBUM_GENRE}, ensure_ascii=False), "utf-8")
            os.replace(tmp, _FILE[0])
        except Exception:
            pass


# ---------------------------------------------------------------- consultas
def _deezer_search(q):
    d = deezer._get(f"{deezer.API}/search?" + urllib.parse.urlencode({"q": q, "limit": 15}), lang="es")
    out = []
    for it in (d.get("data") or []) if isinstance(d, dict) else []:
        if (it.get("type") or "track") != "track":
            continue
        out.append({"artist": (it.get("artist") or {}).get("name") or "", "title": it.get("title") or "",
                    "album": (it.get("album") or {}).get("title") or "", "album_id": (it.get("album") or {}).get("id"),
                    "secs": it.get("duration") or 0, "source": "Deezer", "link": it.get("link") or ""})
    return out


def _deezer_genre(album_id):
    if not album_id:
        return ""
    k = str(album_id)
    if k in _ALBUM_GENRE:
        return _ALBUM_GENRE[k]
    d = deezer._get(f"{deezer.API}/album/{album_id}", lang="es")
    gs = [g.get("name") for g in ((d.get("genres") or {}).get("data") or []) if g.get("name")] if isinstance(d, dict) else []
    _ALBUM_GENRE[k] = gs[0] if gs else ""
    return _ALBUM_GENRE[k]


def _itunes_search(q):
    with _it_lock:
        wait = _ITUNES_GAP - (time.time() - _it_last[0])
        if wait > 0:
            time.sleep(wait)
        _it_last[0] = time.time()
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": q, "entity": "song", "limit": 10, "country": "CO"})
    req = urllib.request.Request(url, headers={"User-Agent": "BrainOrder/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    return [{"artist": it.get("artistName") or "", "title": it.get("trackName") or "", "album": it.get("collectionName") or "",
             "genre": it.get("primaryGenreName") or "", "secs": round((it.get("trackTimeMillis") or 0) / 1000),
             "source": "Apple Music", "link": it.get("trackViewUrl") or ""} for it in d.get("results") or []]


# ---------------------------------------------------------------- comparar
_STOP = {"ft", "feat", "featuring", "x", "y", "and", "the", "el", "la", "los", "las", "de", "remix", "mix", "edit",
         "original", "version", "official", "oficial", "audio", "video", "extended", "radio", "remastered"}


def _words(s):
    return {w for w in norm(s).split() if w not in _STOP and len(w) > 1}


def _score(query, cand):
    """0..1: cuánto de lo que dice tu archivo aparece en artista + título del resultado."""
    q, c = _words(query), _words(cand["artist"] + " " + cand["title"])
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


def _extra(query, cand):
    """0..1: cuánto del resultado NO está en tu archivo (otra versión: «Live», «8-Bit», otro artista…)."""
    q, c = _words(query), _words(cand["artist"] + " " + cand["title"])
    return len(c - q) / len(c) if c else 1.0


def query_for(path, tags):
    """Qué buscar: artista + título si están bien; si no, el nombre del archivo sin «Desconocido -» ni basura."""
    a, t = tags.get("artist") or "", tags.get("title") or ""
    if a and t and not etiquetas.bad_artist(a) and not etiquetas.bad_title(t):
        return etiquetas.clean(f"{a} {t}")
    stem = re.sub(r"\s*\(\d+\)$", "", Path(path).stem)
    if " - " in stem and etiquetas.bad_artist(stem.split(" - ", 1)[0]):
        stem = stem.split(" - ", 1)[1]
    if etiquetas.bad_artist(a) and t and " - " in t:
        stem = t
    s = etiquetas.clean(stem)
    s = re.sub(r"[\[\(][^\]\)]*(remix|edit|mix|version|rmx|bootleg|cover|acoustic|live|en vivo)[^\]\)]*[\]\)]", " ", s, flags=re.I)
    s = re.sub(r"\b(ft|feat|featuring)\.?\s", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s.replace(" - ", " ").replace("_", " ")).strip()


def _key(c):
    return (c["sure"], c["close"], c["score"], -c["extra"])


def _rank(cands, query, secs):
    for c in cands:
        c["score"] = round(_score(query, c), 2)
        c["extra"] = round(_extra(query, c), 2)
        c["close"] = bool(secs and c.get("secs") and abs(secs - c["secs"]) <= TOL)
        c["sure"] = c["close"] and c["score"] >= 0.5
    cands.sort(key=_key, reverse=True)
    return [c for c in cands if c["score"] >= 0.3 or c["close"] and c["score"] >= 0.2]


_VERSION = r"\b(remix|rmx|edit|extended|mix|bootleg|mashup|intro|outro|clean|dirty|explicit|acapella|instrumental|vip|dub|cover|acoustic|live|en vivo|version|versión|oficial|official)\b"


def _queries(q):
    """La búsqueda tal cual y, si no aparece nada, sin las palabras de versión («remix», «edit»…)."""
    out = [q]
    plain = re.sub(r"\s+", " ", re.sub(_VERSION, " ", q, flags=re.I)).strip()
    if plain and plain != q:
        out.append(plain)
    return out


_VER_GROUP = re.compile(r"[\(\[][^\)\]]*\b(remix|rmx|edit|extended|mix|bootleg|mashup|vip|dub|cover|acoustic|live|en vivo|version|versión|remaster\w*)\b[^\)\]]*[\)\]]", re.I)


def keep_version(file_title, cand_title):
    """Si tu archivo es una versión («(K&F Edit)», «Remix») y el resultado es la original, se le deja la versión
    al título para no perder ese dato."""
    ft = etiquetas.clean(file_title or "")
    groups = [m.group(0) for m in _VER_GROUP.finditer(ft)]
    if not groups:
        m = re.search(r"\b(remix|rmx|edit|extended mix|bootleg|mashup|acoustic|en vivo|live)\s*$", ft, re.I)
        groups = [f"({m.group(1).title()})"] if m else []
    out = cand_title
    for g in groups:
        if norm(g) and norm(g) not in norm(out):
            out = f"{out} {g}"
    return out


def _file_title(path, tags):
    """El título según tu archivo (sin el artista): de la etiqueta si está bien, si no del nombre del archivo."""
    a, t = tags.get("artist") or "", tags.get("title") or ""
    if t and not etiquetas.bad_title(t) and a and not etiquetas.bad_artist(a):
        return t
    src = t if t and " - " in t else re.sub(r"\s*\(\d+\)$", "", Path(path).stem)
    if " - " in src and etiquetas.bad_artist(src.split(" - ", 1)[0]):
        src = src.split(" - ", 1)[1]
    sp = etiquetas._split(src)
    return sp[1] if sp else src


def lookup(path, tags=None, query=None, use_cache=True):
    """-> {query, secs, best (o None), cands: [...]} (best = la segura, si hay)."""
    tags = tags if tags is not None else etiquetas.read(path)
    q = (query or "").strip() or query_for(path, tags)
    try:
        st = os.stat(path)
        key = f"{path}|{st.st_size}|{q}"
    except OSError:
        key = f"{path}|{q}"
    c = _CACHE.get(key) if use_cache else None
    if c and (c.get("cands") or time.time() - c.get("t", 0) < NONE_DAYS * 86400):
        return c
    secs = duration(path) if os.path.isfile(path) else None
    cands, errors = [], []
    if q:
        for qq in _queries(q):
            try:
                cands = _rank(_deezer_search(qq), q, secs)
            except Exception as e:
                errors.append(f"Deezer: {e}")
                break
            if cands:
                break
        if not cands or not cands[0]["sure"]:
            for qq in _queries(q):
                try:
                    more = _rank(_itunes_search(qq), q, secs)
                except Exception as e:
                    errors.append(f"Apple Music: {e}")
                    break
                if more:
                    cands = sorted(cands + more, key=_key, reverse=True)
                    break
        for cand in cands[:3]:  # el género del álbum en Deezer (iTunes ya lo trae)
            if cand["source"] == "Deezer" and not cand.get("genre"):
                try:
                    cand["genre"] = _deezer_genre(cand.get("album_id"))
                except Exception:
                    cand["genre"] = ""
    cands = cands[:6]
    file_title = _file_title(path, tags)
    for cand in cands:
        cand.pop("album_id", None)
        cand["title_keep"] = keep_version(file_title, cand["title"])
    out = {"query": q, "secs": round(secs) if secs else None, "cands": cands,
           "best": cands[0] if cands and cands[0]["sure"] else None, "t": time.time()}
    if errors and not cands:
        out["error"] = "; ".join(errors)
        return out  # sin internet: no se guarda (se vuelve a intentar)
    with _LOCK:
        _CACHE[key] = out
    return out
