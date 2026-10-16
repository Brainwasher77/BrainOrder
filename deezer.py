"""Links de Deezer para las canciones que faltan (API pública, sin cuenta).

1) Busca por ISRC (misma grabación que en Spotify).
2) Si no, busca por "artista título" y valida que el artista coincida.
3) Si no aparece, deja un link de búsqueda en Deezer.
Los resultados se guardan en caché para no repetir consultas.
"""
import json
import time
import urllib.parse
import urllib.request

from config import SUPPORT_DIR, log
from biblioteca import norm, core_title

CACHE = SUPPORT_DIR / "deezer_cache.json"
API = "https://api.deezer.com"
_MIN_GAP = 0.12  # ~8 consultas/seg, por debajo del límite de Deezer (50 cada 5 s)
_last = [0.0]


def _get(url):
    wait = _MIN_GAP - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "SpotiSync/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    if isinstance(data, dict) and (data.get("error") or {}).get("code") == 4:  # cuota excedida
        time.sleep(5)
        return _get(url)
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


def add_links(analysis, progress=None, offline=False):
    """Pone row['deezer'] = {url, found, exact} en cada canción que falta.
    offline=True: solo usa lo que ya está guardado (no consulta Deezer)."""
    try:
        cache = json.loads(CACHE.read_text("utf-8"))
    except Exception:
        cache = {}
    missing = {}
    for pl in analysis:
        for r in pl["tracks"]:
            if r["status"] == "missing":
                missing.setdefault(r["id"], r)
    todo = [] if offline else [r for i, r in missing.items() if i not in cache]
    offline = False
    for n, r in enumerate(todo, 1):
        if progress and (n == 1 or n % 10 == 0):
            progress(f"Buscando links de Deezer {n}/{len(todo)}…")
        try:
            res = _lookup(r)
            cache[r["id"]] = res or {"url": None}
        except Exception as e:
            log(f"Deezer no respondió ({e}); se usan links de búsqueda")
            offline = True
            break
        if n % 50 == 0:
            _save(cache)
    if todo and not offline:
        _save(cache)
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


def _save(cache):
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache), "utf-8")
    except Exception:
        pass
