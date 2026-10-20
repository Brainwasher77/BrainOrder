"""Links de Deezer para las canciones que faltan (API pública, sin cuenta).

1) Busca por ISRC (misma grabación que en Spotify).
2) Si no, busca por "artista título" y valida que el artista coincida.
3) Si no aparece, deja un link de búsqueda en Deezer.
Los resultados se guardan en caché para no repetir consultas.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from config import SUPPORT_DIR, log
from biblioteca import norm, core_title

CACHE = SUPPORT_DIR / "deezer_cache.json"
API = "https://api.deezer.com"
_MIN_GAP = 0.12  # ~8 consultas/seg, por debajo del límite de Deezer (50 cada 5 s)
_last = [0.0]


_GAP_LOCK = threading.Lock()


def _get(url, tries=4):
    with _GAP_LOCK:  # varias tareas a la vez respetan juntas el límite de Deezer
        wait = _MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "BrainOrder/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if isinstance(data, dict) and (data.get("error") or {}).get("code") == 4:  # cuota excedida
        if tries <= 1:
            raise RuntimeError("Deezer: límite de consultas")
        time.sleep(5)
        return _get(url, tries - 1)
    return data


def search_url(row):
    q = f"{(row.get('artists') or [''])[0]} {row['name']}".strip()
    return "https://www.deezer.com/search/" + urllib.parse.quote(q)


def _lookup(row):
    isrc = row.get("isrc")
    if isrc:
        d = _get(f"{API}/track/isrc:{urllib.parse.quote(isrc)}")
        if isinstance(d, dict) and d.get("link") and not d.get("error"):
            return {"url": d["link"], "exact": True}
    artist = (row.get("artists") or [""])[0]
    q = f"{artist} {core_title(row['name'])}".strip()
    d = _get(f"{API}/search?" + urllib.parse.urlencode({"q": q, "limit": 5}))
    want_a, want_t = norm(artist), core_title(row["name"])
    for item in (d.get("data") or []) if isinstance(d, dict) else []:
        a = norm((item.get("artist") or {}).get("name", ""))
        if want_a and (want_a in a or a in want_a) and core_title(item.get("title", "")) == want_t:
            return {"url": item["link"], "exact": False}
    return None


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
        if i.startswith("dz:") and r.get("url") and i not in cache:
            with _LOCK:
                cache[i] = {"url": r["url"], "exact": True}
    todo = [] if offline else [r for i, r in missing.items() if i not in cache]
    for n, r in enumerate(todo, 1):
        if progress:
            progress(f"Buscando links de Deezer: {n}/{len(todo)}", n / len(todo))
        if r["id"] in cache:  # otra tarea ya lo buscó mientras tanto
            continue
        try:
            res = _lookup(r)
            with _LOCK:
                cache[r["id"]] = res or {"url": None}
        except Exception as e:
            log(f"Deezer no respondió ({e}); se usan links de búsqueda")
            break
        if n % 50 == 0:
            _save()
    if todo:
        _save()
    for pl in analysis:
        for r in pl["tracks"]:
            if r["status"] != "missing":
                continue
            c = cache.get(r["id"]) or {}
            if c.get("url"):
                r["deezer"] = {"url": c["url"], "found": True, "exact": c.get("exact", False)}
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
        if isinstance(d, dict) and d.get("preview") and not d.get("error"):
            out = d
    if out is None:
        q = f"{artist} {core_title(title)}".strip()
        d = _get(f"{API}/search?" + urllib.parse.urlencode({"q": q, "limit": 8}))
        want_a, want_t = norm(artist), core_title(title)
        items = [i for i in ((d.get("data") or []) if isinstance(d, dict) else []) if i.get("preview")]
        for item in items:
            a = norm((item.get("artist") or {}).get("name", ""))
            if (not want_a or want_a in a or a in want_a) and core_title(item.get("title", "")) == want_t:
                out = item
                break
    res = {"preview": out["preview"], "link": out.get("link"),
           "title": f"{(out.get('artist') or {}).get('name', '')} - {out.get('title', '')}"} if out else None
    _PREV[key] = (time.time(), res)
    return res
