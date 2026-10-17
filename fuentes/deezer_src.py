"""Deezer como fuente: playlists públicas de un perfil y/o links de playlists (API pública, sin login)."""
import json
import re
import time
import urllib.parse
import urllib.request

KEY = "deezer"
LABEL = "Deezer"
PREFIX = "dz:"
API = "https://api.deezer.com"
_last = [0.0]


class DeezerError(Exception):
    pass


def _get(url, tries=3):
    wait = 0.12 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "SpotiSync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        if tries > 1:
            time.sleep(1.5)
            return _get(url, tries - 1)
        raise DeezerError(f"Deezer no respondió: {e}")
    err = data.get("error") if isinstance(data, dict) else None
    if err:
        if err.get("code") == 4 and tries > 1:  # cuota: esperar y reintentar
            time.sleep(5)
            return _get(url, tries - 1)
        raise DeezerError(f"Deezer: {err.get('message') or err}")
    return data


def _paged(url, on_page=None):
    out = []
    while url:
        d = _get(url)
        out += d.get("data") or []
        if on_page:
            on_page(len(out), d.get("total"))
        url = d.get("next")
    return out


def _resolve(text):
    """Acepta id, URL normal o link corto (link.deezer.com / deezer.page.link). -> (tipo, id)"""
    t = (text or "").strip()
    if not t:
        return None, None
    if re.fullmatch(r"\d+", t):
        return "user", t
    if re.search(r"(link\.deezer\.com|deezer\.page\.link)", t):
        try:
            req = urllib.request.Request(t, headers={"User-Agent": "SpotiSync/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                t = r.geturl()
        except Exception:
            return None, None
    m = re.search(r"deezer\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?(profile|user|playlist)/(\d+)", t)
    if not m:
        return None, None
    return ("playlist" if m.group(1) == "playlist" else "user"), m.group(2)


def enabled(cfg):
    s = (cfg.get("sources") or {}).get(KEY) or {}
    return bool(s.get("enabled") and (s.get("user") or s.get("playlists")))


def _meta(p, liked=False):
    return {"id": PREFIX + str(p["id"]), "name": p.get("title") or "Deezer", "source": KEY,
            "snapshot": str(p.get("checksum") or p.get("nb_tracks") or ""), "total": p.get("nb_tracks"),
            "url": p.get("link"), "liked": liked}


def check(cfg_src):
    """Valida lo que escribió el usuario. -> {user: nombre|None, playlists: [nombres], errors: []}"""
    out = {"user": None, "playlists": [], "errors": []}
    kind, uid = _resolve(cfg_src.get("user", ""))
    if cfg_src.get("user"):
        if kind != "user":
            out["errors"].append("No reconozco ese perfil de Deezer. Pega el link de tu perfil o tu número de usuario.")
        else:
            try:
                out["user"] = _get(f"{API}/user/{uid}").get("name")
            except DeezerError as e:
                out["errors"].append(str(e))
    for link in cfg_src.get("playlists") or []:
        kind, pid = _resolve(link)
        if kind != "playlist":
            out["errors"].append(f"No es un link de playlist de Deezer: {link}")
            continue
        try:
            out["playlists"].append(_get(f"{API}/playlist/{pid}").get("title"))
        except DeezerError as e:
            out["errors"].append(f"{link}: {e}")
    return out


def list_playlists(cfg, progress=None):
    s = (cfg.get("sources") or {}).get(KEY) or {}
    metas, seen = [], set()
    kind, uid = _resolve(s.get("user", ""))
    if kind == "user":
        if progress:
            progress("Leyendo tus playlists de Deezer…")
        for p in _paged(f"{API}/user/{uid}/playlists?limit=100"):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            loved = bool(p.get("is_loved_track"))
            m = _meta(p, liked=loved)
            if loved:
                m["name"] = s.get("loved_name") or "Favoritos de Deezer"
            if loved and not s.get("include_loved", True):
                continue
            metas.append(m)
    for link in s.get("playlists") or []:
        kind, pid = _resolve(link)
        if kind != "playlist" or int(pid) in seen:
            continue
        seen.add(int(pid))
        try:
            metas.append(_meta(_get(f"{API}/playlist/{pid}")))
        except DeezerError:
            continue
    return metas


def _track(t):
    artists = [(t.get("artist") or {}).get("name", "")]
    return {"id": PREFIX + str(t.get("id")), "name": t.get("title") or "", "artists": [a for a in artists if a],
            "album": (t.get("album") or {}).get("title", ""), "duration_ms": int(t.get("duration") or 0) * 1000,
            "url": t.get("link") or "", "isrc": t.get("isrc") or ""}


def tracks(cfg, meta, progress=None):
    pid = meta["id"][len(PREFIX):]
    total = meta.get("total") or 0

    def on_page(n, tot):
        if progress:
            progress(f"Leyendo «{meta['name']}» de Deezer: {n}/{tot or total}", n / max(1, tot or total or n))
    rows = _paged(f"{API}/playlist/{pid}/tracks?limit=100", on_page)
    return [_track(t) for t in rows if t.get("type", "track") == "track"]
