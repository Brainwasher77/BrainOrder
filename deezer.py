"""Links de Deezer para las canciones que faltan (API pública, sin cuenta).

1) Busca por ISRC (misma grabación que en Spotify).
2) Si no, busca por "artista título" y valida que el artista coincida.
3) Si no aparece, deja un link de búsqueda en Deezer.
Los resultados se guardan en caché para no repetir consultas.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from config import SUPPORT_DIR, log
from biblioteca import norm, core_title, extras, version_diff, same_length

CACHE = SUPPORT_DIR / "deezer_cache.json"
API = "https://api.deezer.com"
_MIN_GAP = 0.12  # ~8 consultas/seg, por debajo del límite de Deezer (50 cada 5 s)
_last = [0.0]


_GAP_LOCK = threading.Lock()


def _get(url, tries=4, lang=None):
    with _GAP_LOCK:  # varias tareas a la vez respetan juntas el límite de Deezer
        wait = _MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    headers = {"User-Agent": "BrainOrder/1.0"}
    if lang:
        headers["Accept-Language"] = lang  # p. ej. géneros en español («Música africana», «Películas/Juegos»)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if isinstance(data, dict) and (data.get("error") or {}).get("code") == 4:  # cuota excedida
        if tries <= 1:
            raise RuntimeError("Deezer: límite de consultas")
        time.sleep(5)
        return _get(url, tries - 1, lang)
    return data


def search_url(row):
    q = f"{(row.get('artists') or [''])[0]} {row['name']}".strip()
    return "https://www.deezer.com/search/" + urllib.parse.quote(q)


V = 3  # versión del criterio: los links guardados con uno anterior (incluidos los de ISRC) se comprueban otra vez


def _artist_ok(want, item):
    """El artista de tu canción está entre los de Deezer (principal o colaboradores)."""
    w = norm(want)
    if not w:
        return True
    names = [(item.get("artist") or {}).get("name", "")] + [c.get("name", "") for c in item.get("contributors") or []]
    for n in names:
        a = norm(n)
        if a and (w == a or (min(len(w), len(a)) >= 3 and (w in a or a in w))):
            return True
    return False


def matches(row, item):
    """¿Ese track de Deezer es la canción de la fila? Mismo título base y mismo artista; si hay duración en
    los dos, que no esté lejísimos (otra canción con el mismo nombre). Sirve para comprobar cualquier link."""
    if not item or item.get("error") or not item.get("id"):
        return False
    if core_title(item.get("title", "")) != core_title(row.get("name", "")) \
            and core_title(item.get("title_short", "")) != core_title(row.get("name", "")):
        return False
    if not _artist_ok((row.get("artists") or [""])[0], item):
        return False
    tdur = (row.get("duration_ms") or 0) / 1000
    if tdur and item.get("duration") and abs(item["duration"] - tdur) > max(45, 0.25 * tdur):
        return False
    return True


def track_id(url):
    """Número del track en un link de Deezer (www.deezer.com/xx/track/123 → 123)."""
    m = re.search(r"deezer\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?track/(\d+)", url or "")
    return m.group(1) if m else None


def check_link(row, url):
    """Abre el link en la API de Deezer y dice si lleva a la canción de la fila. -> True/False/None (sin respuesta)"""
    tid = track_id(url)
    if not tid:
        return False
    try:
        return matches(row, _get(f"{API}/track/{tid}"))
    except Exception:
        return None


def _pick(row, items):
    """De los resultados de Deezer, la MISMA versión que la canción de tu playlist: mismo título base y artista,
    sin palabras de otra versión (remix, dream version, extended…) y con la misma duración.
    -> (item, misma_version) o (None, False)"""
    artist = (row.get("artists") or [""])[0]
    want_a, want_t, ex = norm(artist), core_title(row["name"]), extras(row["name"])
    tdur = (row.get("duration_ms") or 0) / 1000 or None
    cands = []
    for item in items:
        a = norm((item.get("artist") or {}).get("name", ""))
        if not (want_a and a and (want_a in a or a in want_a)) or core_title(item.get("title", "")) != want_t:
            continue
        fx = extras(item.get("title", ""))
        same_v = (ex <= fx or fx <= ex) and not version_diff(ex, fx)
        same_len = same_length(tdur, item.get("duration")) if tdur and item.get("duration") else True
        dd = abs((item.get("duration") or 0) - tdur) if tdur and item.get("duration") else 0
        # igual que lo acepta BrainOrder al reconocer el archivo: mismo título exacto, o una variante
        # (radio edit…) con la misma duración. Lo demás es otra versión (remix, dream version…).
        tier = 0 if ex == fx and same_len else 1 if ex == fx else 2 if same_v and same_len else 3
        cands.append((tier, dd, item))
    if not cands:
        return None, False
    best = min(cands, key=lambda c: c[:2])
    return best[2], best[0] < 3


def _label(row):
    return f"{(row.get('artists') or [''])[0]} - {row.get('name', '')}"


def _lookup(row):
    isrc = row.get("isrc")
    if isrc:
        d = _get(f"{API}/track/isrc:{urllib.parse.quote(isrc)}")
        # el ISRC a veces está repetido (sellos que lo reutilizan): solo vale si de verdad es esa canción
        if isinstance(d, dict) and d.get("link") and not d.get("error") and matches(row, d):
            return {"url": d["link"], "exact": True, "v": V, "for": _label(row)}
    artist = (row.get("artists") or [""])[0]
    q = f"{artist} {core_title(row['name'])}".strip()
    d = _get(f"{API}/search?" + urllib.parse.urlencode({"q": q, "limit": 25}))
    item, same = _pick(row, (d.get("data") or []) if isinstance(d, dict) else [])
    if item is None:
        return None
    out = {"url": item["link"], "exact": False, "v": V, "for": _label(row)}
    if not same:  # Deezer no tiene esa versión: el link es de otra (se avisa para que no te confunda)
        dur = item.get("duration") or 0
        out["other"] = f"{item.get('title', '')} ({dur // 60}:{dur % 60:02d})"
    return out


_LOCK = threading.Lock()
_MEM = {}
_LOADED = [False]


def _cache():
    """Caché compartido por todas las tareas (varias pueden buscar links a la vez)."""
    with _LOCK:
        if not _LOADED[0]:
            try:
                _MEM.update(json.loads(CACHE.read_text("utf-8")))
            except Exception:
                pass
            _LOADED[0] = True
    return _MEM


def add_links(analysis, progress=None, offline=False):
    """Pone row['deezer'] = {url, found, exact} en cada canción que falta.
    offline=True: solo usa lo que ya está guardado (no consulta Deezer)."""
    cache = _cache()
    missing = {}
    for pl in analysis:
        for r in pl["tracks"]:
            if r["status"] == "missing":
                missing.setdefault(r["id"], r)
    for i, r in missing.items():  # canciones que vienen de Deezer: ya traen su link
        if i.startswith("dz:") and r.get("url") and (i not in cache or cache[i].get("v") != V):
            with _LOCK:
                cache[i] = {"url": r["url"], "exact": True, "v": V, "for": _label(r)}
    # guardado con un criterio anterior, o para otra canción (el id se reutilizó): se comprueba otra vez
    stale = (lambda c, r: c.get("v") != V or (c.get("for") and c.get("url") and norm(c["for"]) != norm(_label(r))))
    todo = [] if offline else [r for i, r in missing.items() if i not in cache or stale(cache[i], r)]
    fixed = kept = 0
    for n, r in enumerate(todo, 1):
        if progress:
            progress(f"Buscando links de Deezer: {n}/{len(todo)}", n / len(todo))
        old = cache.get(r["id"])
        if old and not stale(old, r):  # otra tarea ya lo buscó mientras tanto
            continue
        try:
            res = None
            if old and old.get("url") and check_link(r, old["url"]):  # el link viejo sí era: se conserva
                res = {**old, "v": V, "for": _label(r)}
                kept += 1
            if res is None:
                res = _lookup(r)
                if old and old.get("url") and (res or {}).get("url") != old["url"]:
                    fixed += 1
            with _LOCK:
                cache[r["id"]] = res or {"url": None}
        except Exception as e:
            log(f"Deezer no respondió ({e}); se usan links de búsqueda")
            break
        if n % 50 == 0:
            _save()
    if todo:
        _save()
    if fixed or kept:
        log(f"Links de Deezer comprobados: {kept} estaban bien, {fixed} se corrigieron")
    for pl in analysis:
        for r in pl["tracks"]:
            if r["status"] != "missing":
                continue
            c = cache.get(r["id"]) or {}
            if c.get("url") and not stale(c, r):  # sin comprobar todavía: búsqueda, nunca un link que puede ser de otra
                r["deezer"] = {"url": c["url"], "found": True, "exact": c.get("exact", False)}
                if c.get("other"):
                    r["deezer"]["other"] = c["other"]
            else:
                r["deezer"] = {"url": search_url(r), "found": False, "exact": False}
    return analysis


def _save():
    try:
        with _LOCK:
            data = json.dumps(_MEM)
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_name(f".{CACHE.name}.{threading.get_ident()}.tmp")
            tmp.write_text(data, "utf-8")
            os.replace(tmp, CACHE)
    except Exception:
        pass


_PREV = {}


def preview(artist, title, isrc=""):
    """Vista previa de 30 s de Deezer (para canciones que todavía no tienes). -> {"preview", "link", "title"} o None"""
    key = (isrc or "", norm(artist), core_title(title))
    hit = _PREV.get(key)
    if hit and time.time() - hit[0] < 600:  # los links de Deezer vencen pronto: se renuevan cada 10 min
        return hit[1]
    out = None
    if isrc:
        d = _get(f"{API}/track/isrc:{urllib.parse.quote(isrc)}")
        if isinstance(d, dict) and d.get("preview") and not d.get("error") and matches({"name": title, "artists": [artist]}, d):
            out = d
    if out is None:
        q = f"{artist} {core_title(title)}".strip()
        d = _get(f"{API}/search?" + urllib.parse.urlencode({"q": q, "limit": 8}))
        items = [i for i in ((d.get("data") or []) if isinstance(d, dict) else []) if i.get("preview")]
        out, _same = _pick({"name": title, "artists": [artist]}, items)
    res = {"preview": out["preview"], "link": out.get("link"),
           "title": f"{(out.get('artist') or {}).get('name', '')} - {out.get('title', '')}"} if out else None
    _PREV[key] = (time.time(), res)
    return res
