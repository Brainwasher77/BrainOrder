"""Playlists exportadas a archivo: la puerta para SoundCloud, Tidal, Apple Music o cualquier servicio.

Se pone una carpeta («Playlists exportadas») y cada archivo que caiga ahí es una playlist:
  - .m3u / .m3u8             (casi todos los programas y servicios)
  - .csv                     (Exportify, TuneMyMusic, Soundiiz… si trae columna de playlist, salen varias)
  - .txt / .tsv              (Apple Music: Archivo → Biblioteca → Exportar playlist…)
"""
import csv
import hashlib
import io
import os
import re
from pathlib import Path

KEY = "archivos"
LABEL = "Archivos exportados"
PREFIX = "file:"
EXTS = {".m3u", ".m3u8", ".csv", ".txt", ".tsv"}

COLS = {
    "title": ["track name", "track title", "song name", "name", "title", "track", "song", "nombre", "titulo", "cancion"],
    "artist": ["artist name s", "artist names", "artist name", "artists", "artist", "artista", "artistas", "creator"],
    "album": ["album name", "album", "album title"],
    "duration": ["duration ms", "duration_ms", "track duration ms", "duration", "time", "length", "duracion", "tiempo"],
    "isrc": ["isrc"],
    "playlist": ["playlist name", "playlist", "lista", "playlist title"],
    "url": ["track url", "url", "link", "track uri", "spotify uri", "uri"],
}


def enabled(cfg):
    s = (cfg.get("sources") or {}).get(KEY) or {}
    return bool(s.get("enabled") and s.get("folder"))


def _norm(s):
    s = (s or "").lower().replace("(", " ").replace(")", " ")
    s = re.sub(r"[^a-z0-9_ ]+", " ", s.translate(str.maketrans("áéíóúñ", "aeioun")))
    return re.sub(r"\s+", " ", s).strip()


def _read_text(p: Path):
    raw = p.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _ms(v):
    v = (v or "").strip()
    if not v:
        return 0
    if ":" in v:  # 3:45 o 1:03:45
        secs = 0
        for part in v.split(":"):
            try:
                secs = secs * 60 + float(part)
            except ValueError:
                return 0
        return int(secs * 1000)
    try:
        n = float(v.replace(",", "."))
    except ValueError:
        return 0
    return int(n if n > 10_000 else n * 1000)  # Exportify da ms; Apple Music da segundos


def _split_artists(v):
    parts = re.split(r"\s*(?:;|,|\s&\s|\sx\s|\sfeat\.?\s|\sft\.?\s)\s*", v or "", flags=re.I)
    return [a.strip() for a in parts if a.strip()]


def _tid(artists, title):
    key = (_norm(" ".join(artists[:1])) + "|" + _norm(title)).encode()
    return PREFIX + hashlib.sha1(key).hexdigest()[:16]


def _track(title, artists, album="", ms=0, isrc="", url=""):
    if " - " in title and not artists:
        a, title = title.split(" - ", 1)
        artists = [a.strip()]
    title = title.strip()
    if url.startswith("spotify:track:"):
        url = "https://open.spotify.com/track/" + url.rsplit(":", 1)[1]
    return {"id": ("isrc:" + isrc.upper()) if isrc else _tid(artists, title), "name": title,
            "artists": artists, "album": album, "duration_ms": ms, "url": url if url.startswith("http") else "",
            "isrc": isrc.upper()}


def parse_m3u(text, default_name):
    name, out, pending = default_name, [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("#PLAYLIST:"):
            name = line.split(":", 1)[1].strip() or name
        elif line.upper().startswith("#EXTINF:"):
            info = line.split(":", 1)[1]
            secs, _, label = info.partition(",")
            try:
                ms = int(float(secs.split()[0]) * 1000) if secs.strip() and float(secs.split()[0]) > 0 else 0
            except ValueError:
                ms = 0
            pending = (label.strip(), ms)
        elif line.startswith("#"):
            continue
        else:
            if pending and pending[0]:
                label, ms = pending
            else:
                label, ms = Path(line.split("?")[0]).stem, 0
            artists, title = [], label
            if " - " in label:
                a, title = label.split(" - ", 1)
                artists = _split_artists(a)
            out.append(_track(title, artists, ms=ms, url=line))
            pending = None
    return {name: out}


def parse_table(text, default_name):
    sample = text[:4096]
    delim = "\t" if sample.count("\t") > sample.count(",") else (";" if sample.count(";") > sample.count(",") else ",")
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        return {}
    head = [_norm(h) for h in rows[0]]
    col = {}
    for key, names in COLS.items():
        for n in names:
            if n in head:
                col[key] = head.index(n)
                break
    if "title" not in col:
        raise ValueError("no encontré una columna de título (Track name / Name / Title)")
    out = {}

    def g(r, k):
        i = col.get(k)
        return r[i].strip() if i is not None and i < len(r) else ""
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        title = g(r, "title")
        if not title:
            continue
        pl = g(r, "playlist") or default_name
        out.setdefault(pl, []).append(_track(title, _split_artists(g(r, "artist")), g(r, "album"),
                                             _ms(g(r, "duration")), g(r, "isrc"), g(r, "url")))
    return out


def parse_file(p: Path):
    text = _read_text(p)
    if p.suffix.lower() in (".m3u", ".m3u8"):
        return parse_m3u(text, p.stem)
    return parse_table(text, p.stem)


def _files(folder):
    root = Path(folder)
    if not root.is_dir():
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames):
            if not fn.startswith(".") and Path(fn).suffix.lower() in EXTS:
                out.append(Path(dirpath) / fn)
    return out


def _pid(root, p, name):
    rel = str(p.relative_to(root)).replace("\\", "/")
    return PREFIX + hashlib.sha1(f"{rel}::{name}".encode()).hexdigest()[:16]


def list_playlists(cfg, progress=None):
    s = (cfg.get("sources") or {}).get(KEY) or {}
    root = Path(s.get("folder") or "")
    metas = []
    for p in _files(root):
        try:
            st = p.stat()
            lists = parse_file(p)
        except Exception as e:
            metas.append({"id": _pid(root, p, p.stem), "name": f"{p.stem} (no se pudo leer)", "source": KEY,
                          "error": str(e), "file": str(p), "snapshot": None, "total": 0})
            continue
        for name, tr in lists.items():
            metas.append({"id": _pid(root, p, name), "name": name, "source": KEY, "file": str(p),
                          "snapshot": f"{st.st_size}:{int(st.st_mtime)}", "total": len(tr)})
    return metas


def tracks(cfg, meta, progress=None):
    p = Path(meta.get("file") or "")
    if not p.exists():
        raise FileNotFoundError(f"Ya no existe {p}")
    lists = parse_file(p)
    if progress:
        progress(f"Leyendo «{meta['name']}» de {p.name}…", 1)
    root = Path(((cfg.get("sources") or {}).get(KEY) or {}).get("folder") or p.parent)
    for name, tr in lists.items():
        if _pid(root, p, name) == meta["id"]:
            return tr
    return lists.get(meta["name"], [])
