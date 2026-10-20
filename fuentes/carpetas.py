"""Playlists importadas sin plataforma: una carpeta de tu computador o una playlist que creaste en un
programa de DJ (Rekordbox, Traktor, Serato, Engine DJ).

BrainOrder las trata como cualquier otra playlist (estadísticas, faltantes, organizar, otros programas…).
- Carpeta: sus canciones son los audios de la carpeta, en orden alfabético.
- Programa de DJ: sus canciones son las de esa playlist en el programa, en su orden (se relee en cada análisis).
Ajuste: cfg["folder_playlists"] = [{"name", "path"} | {"name", "program", "ref"}].

Carpetas: la playlist RECUERDA sus canciones (SUPPORT/miembros.json). Si borras o mueves un archivo de la
carpeta (por ejemplo porque ya lo tienes en otra playlist), la canción sigue en la playlist usando la otra
copia, igual que en Rekordbox. Solo sale si ya no existe en ninguna parte de tu música o si la quitas tú
(clic derecho → Quitar de esta playlist).
"""
import hashlib
import json
import os
import threading
from pathlib import Path

KEY = "carpetas"
LABEL = "Importadas"
PREFIX = "dir:"


_MLOCK = threading.Lock()


def _mfile():
    from config import SUPPORT_DIR
    return SUPPORT_DIR / "miembros.json"


def _mload():
    try:
        d = json.loads(_mfile().read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _msave(d):
    from config import write_atomic
    _mfile().parent.mkdir(parents=True, exist_ok=True)
    write_atomic(_mfile(), json.dumps(d, ensure_ascii=False))


def members(pid):
    return list(_mload().get(pid) or [])


def remember(pid, files):
    """Suma a la memoria de la playlist los archivos que tiene ahora."""
    with _MLOCK:
        d = _mload()
        cur = set(d.get(pid) or [])
        new = cur | set(files)
        if new != cur:
            d[pid] = sorted(new)
            _msave(d)


def forget(pid, paths):
    with _MLOCK:
        d = _mload()
        gone = set(paths)
        d[pid] = [m for m in d.get(pid) or [] if m not in gone]
        _msave(d)


def remap(moved):
    """Archivos que BrainOrder movió: la memoria de las playlists pasa a la ruta nueva."""
    if not moved:
        return
    with _MLOCK:
        d = _mload()
        changed = False
        for pid, paths in d.items():
            new = sorted({moved.get(p, p) for p in paths})
            if new != sorted(paths):
                d[pid], changed = new, True
        if changed:
            _msave(d)


def member_paths(cfg, e, memo=None):
    """Canciones de la playlist importada: lo que hay en la carpeta + lo que tenía y borraste o moviste
    (esas se siguen usando desde la otra copia). Para programas de DJ, lo que diga el programa."""
    files = _paths(cfg, e, memo if memo is not None else {})
    if files is None or not e.get("path"):
        return files
    pid = entry_pid(e)
    remember(pid, files)
    have = set(files)
    gone = [m for m in members(pid) if m not in have]  # borradas o en otra carpeta: siguen en la playlist
    return sorted(files + gone, key=lambda p: p.lower())


def entries(cfg):
    return [e for e in cfg.get("folder_playlists") or [] if e.get("path") or (e.get("program") and e.get("ref"))]


def entry_pid(e):
    if e.get("path"):
        return pid_for(e["path"])
    return dj_pid(e["program"], e["ref"])


def dj_pid(program, ref):
    return PREFIX + hashlib.sha1(f"{program}:{ref}".encode("utf-8")).hexdigest()[:14]


def enabled(cfg):
    return bool(entries(cfg))


def pid_for(path):
    return PREFIX + hashlib.sha1(os.path.normcase(os.path.normpath(str(path))).encode("utf-8")).hexdigest()[:14]


def audio_files(folder, excluder=None):
    """Audios de la carpeta (incluye subcarpetas), en orden alfabético."""
    import biblioteca
    try:
        return sorted(biblioteca.walk_audio(folder, excluder), key=lambda p: p.lower())
    except OSError:
        return []


def _snapshot(files):
    newest = 0
    for f in files:
        try:
            newest = max(newest, int(os.stat(f).st_mtime))
        except OSError:
            pass
    return f"{len(files)}:{newest}"


def _dj_lists(cfg, program, memo):
    if program not in memo:
        import dj_playlists
        memo[program] = dj_playlists.read(cfg, program) or {}
    return memo[program]


def _paths(cfg, e, memo):
    """Rutas de la playlist importada (None si ya no existe)."""
    if e.get("path"):
        p = Path(e["path"])
        return audio_files(p) if p.is_dir() else None
    pl = _dj_lists(cfg, e["program"], memo).get(str(e["ref"]))
    return list(pl["paths"]) if pl else None


def list_playlists(cfg, progress=None):
    out, memo = [], {}
    for e in entries(cfg):
        files = _paths(cfg, e, memo)
        if files is None:
            continue
        meta = {"id": entry_pid(e), "name": e.get("name") or Path(e.get("path") or "").name, "source": KEY,
                "snapshot": _snapshot(files), "total": len(files), "url": None}
        if e.get("path"):
            meta["folder"] = str(e["path"])  # su carpeta es la suya, no una nueva en la carpeta de playlists
        if e.get("program"):
            meta["origin"] = e["program"]
            meta["snapshot"] = f"{len(files)}:" + hashlib.sha1("\n".join(files).encode("utf-8")).hexdigest()[:12]
        out.append(meta)
    return out


def track_id(path):
    """Id de la canción del archivo (por artista + título del nombre), sin leer el audio."""
    import biblioteca
    artist, title = biblioteca.parse_file(Path(path))
    key = (biblioteca.norm(artist) + "|" + biblioteca.norm(title)).encode("utf-8")
    return PREFIX + hashlib.sha1(key).hexdigest()[:16]


def track_for(path):
    """Archivo -> canción con el formato de las demás fuentes."""
    import biblioteca
    p = Path(path)
    artist, title = biblioteca.parse_file(p)
    secs = biblioteca.duration(str(p))
    key = (biblioteca.norm(artist) + "|" + biblioteca.norm(title)).encode("utf-8")
    return {"id": PREFIX + hashlib.sha1(key).hexdigest()[:16], "name": title or p.stem,
            "artists": [artist] if artist else [], "album": "", "duration_ms": int((secs or 0) * 1000),
            "url": "", "isrc": ""}


def tracks(cfg, meta, progress=None):
    e = next((x for x in entries(cfg) if entry_pid(x) == meta["id"]), None)
    if not e:
        return []
    files = member_paths(cfg, e) or []
    out, seen = [], set()
    for n, f in enumerate(files, 1):
        if progress and n % 50 == 0:
            progress(f"Leyendo «{meta['name']}»: {n}/{len(files)}", n / len(files))
        t = track_for(f)
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    return out
