"""Tu carpeta de playlists ordenada IGUAL que en Rekordbox, y sin perder nada si le cambias el nombre.

1) Carpetas como en Rekordbox (cfg "rb_mirror", por defecto activo)
   Si dentro de la carpeta de BrainOrder en Rekordbox metes tus playlists en subcarpetas
   (Techno / Hard Techno, Latino / Salsa…), en el disco quedan igual:
       <carpeta de playlists>/Techno/Hard Techno/<canciones>
   Las subcarpetas («Techno») son solo contenedores: no son playlists ni se cuentan como una playlist
   grande con todo lo de adentro.
   cfg "rb_tree"  {pid: ["Techno", "Hard"]}  ruta de subcarpetas de cada playlist en Rekordbox
   cfg "pl_dirs"  {pid: carpeta}             dónde quedó cada playlist la última vez (para mudarla si la
                                             cambias de subcarpeta en Rekordbox)

2) Le cambiaste el nombre a la carpeta de playlists (en Finder / Explorador)
   BrainOrder la reconoce (está al lado y tiene tus mismas carpetas), toma el nombre nuevo y corrige TODAS
   las rutas guardadas (playlists de carpeta, cachés, Historial, la foto de Rekordbox) y las rutas de las
   canciones en Rekordbox y tus otros programas. Así nada aparece como «nuevo» ni «perdido».
"""
import json
import os
from pathlib import Path

from config import SUPPORT_DIR, log, safe_name

JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


# ------------------------------------------------------------------ árbol de Rekordbox -> carpetas
def trails(state, baseline, analysis, ref_pids=None):
    """{pid: [subcarpetas]} de las playlists que están dentro de subcarpetas en Rekordbox.
    state = rb_cambios.read_state (con "folder"); baseline = foto {rid: {pid}}; analysis para casar por nombre."""
    by_name = {}
    for p in analysis or []:
        by_name.setdefault(p["name"], p["id"])
    out = {}
    for rid, v in (state or {}).items():
        trail = [x for x in v.get("folder") or [] if x]
        # solo por id (foto de Rekordbox o playlist leída de Rekordbox): por nombre podía tomar otra que se
        # llama igual (tu «Pop latino» de Spotify no es MGNO/Pop latino)
        pid = (ref_pids or {}).get(rid) or (baseline.get(rid) or {}).get("pid")
        if pid and trail and pid not in out:
            out[pid] = trail
    return out


def parent_for(dest_root, trail):
    p = Path(dest_root)
    for part in trail or []:
        p = p / safe_name(part)
    return p


def direct_files(folder):
    """Archivos que están directamente en la carpeta (no los de sus subcarpetas, que son otras playlists)."""
    try:
        import orden
        return sorted((f for f in Path(folder).iterdir() if f.is_file() and not f.name.startswith(".")
                       and f.name not in JUNK and not (orden.is_list_file(f.name) and orden.is_ours(f))),
                      key=lambda f: f.name.lower())
    except OSError:
        return []


def inside(child, parent):
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def homes_of(analysis):
    """{archivo: carpeta hogar} según el análisis (cada canción vive en una sola carpeta)."""
    out = {}
    for a in analysis or []:
        for r in a.get("tracks") or []:
            if r.get("source") and r.get("dest_dir"):
                out.setdefault(_norm(r["source"]), r["dest_dir"])
    return out


def plan(analysis, cfg, dir_pids=(), resolve=None, pinned=()):
    """Qué hay que mudar para que el disco quede como Rekordbox.
    -> [{"pid", "name", "from", "to", "files": [rutas]}] y {pid: carpeta} de las que ya están donde van.
    Solo se mueve un archivo a la carpeta de una playlist si su hogar ES esa carpeta: así una carpeta vieja
    que ahora es de otra playlist no se vacía de lo que es de esa otra."""
    dest = Path(cfg["dest_root"])
    prev = cfg.get("pl_dirs") or {}
    tree = cfg.get("rb_tree") or {}
    homes = homes_of(analysis)
    pinned = {_norm(p) for p in pinned or ()}
    moves, settled = [], {}
    targets = {_norm(a["folder"]) for a in analysis if a.get("folder")}
    for a in analysis:
        to = a.get("folder")
        if not to or a.get("ignored") or a["id"] in dir_pids or not inside(to, dest):
            continue
        files = {}
        cands = []
        old = prev.get(a["id"])
        if old:
            cands.append(old)
        if a["id"] in tree or old:
            flat = resolve(dest, a["name"]) if resolve else dest / safe_name(a["name"])
            cands.append(str(flat))
        for c in cands:
            # la carpeta vieja de esta playlist: lo que tiene y es de esta playlist (o de nadie, si la carpeta
            # no es de otra playlist) se muda
            if c and _norm(c) != _norm(to) and os.path.isdir(c) and inside(c, dest):
                someone = _norm(c) in targets
                for f in direct_files(c):
                    h = homes.get(_norm(f))
                    if (h and _norm(h) == _norm(to)) or (not h and not someone):
                        files.setdefault(str(f), c)
        if a["id"] in tree:
            # playlists de tus subcarpetas de Rekordbox: su música vuelve a su carpeta aunque esté en la de otra
            for r in a.get("tracks") or []:
                src = r.get("source")
                if src and r.get("status") == "elsewhere" and r.get("dest_dir") and \
                        _norm(r["dest_dir"]) == _norm(to) and inside(src, dest) and _norm(src) not in pinned \
                        and os.path.isfile(src) and _norm(os.path.dirname(src)) != _norm(to):
                    files.setdefault(str(src), os.path.dirname(src))
        if not files:
            settled[a["id"]] = to
            continue
        froms = sorted(set(files.values()))
        moves.append({"pid": a["id"], "name": a["name"], "from": froms[0], "froms": froms, "to": to,
                      "files": sorted(files)})
    return moves, settled


# ------------------------------------------------------------------ carpeta de playlists renombrada
def find_renamed(old_root, names, min_hits=3):
    """old_root ya no existe: ¿está al lado con otro nombre? Se reconoce porque tiene tus mismas carpetas.
    names = nombres de las carpetas de tus playlists. -> ruta nueva o None"""
    old = Path(old_root)
    if old.exists() or not old.parent.is_dir():
        return None
    want = {n.casefold() for n in names if n}
    if not want:
        return None
    best, score = None, 0
    try:
        sibs = [d for d in old.parent.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except OSError:
        return None
    for d in sibs:
        try:
            have = {x.name.casefold() for x in d.iterdir() if x.is_dir()}
        except OSError:
            continue
        hit = len(want & have)
        if hit > score:
            best, score = d, hit
    if best is not None and score >= max(min_hits, len(want) // 2):
        return best
    return None


def same_folders(old_names, new_root, min_hits=3):
    """¿La carpeta nueva tiene las carpetas de tus playlists? (para saber si es la misma con otro nombre)"""
    try:
        have = {x.name.casefold() for x in Path(new_root).iterdir() if x.is_dir()}
    except OSError:
        return False
    want = {n.casefold() for n in old_names if n}
    hit = len(want & have)
    return bool(want) and hit >= max(min_hits, len(want) // 2)


def _swap(s, old, new, direct_only):
    """Cambia el comienzo de una ruta (old -> new). direct_only: solo old y lo que está directamente en old."""
    if s == old:
        return new
    if s.startswith(old + os.sep) or (os.sep != "/" and s.startswith(old + "/")):
        rest = s[len(old) + 1:]
        if direct_only and ("/" in rest or os.sep in rest):
            return s
        return new + os.sep + rest
    return s


def rewrite(obj, prefixes, exact=None, direct_only=False):
    """Recorre JSON (dict/list/str) cambiando rutas que empiezan con alguna de prefixes {viejo: nuevo}
    (también en las claves) y textos exactos de exact {viejo: nuevo} (ids de playlists de carpeta)."""
    exact = exact or {}
    items = sorted(prefixes.items(), key=lambda kv: -len(kv[0]))

    def s(x):
        if x in exact:
            return exact[x]
        for o, n in items:
            y = _swap(x, o, n, direct_only)
            if y is not x and y != x:
                return y
            if os.name == "nt":  # claves normalizadas (normcase) en Windows
                lo = o.lower()
                if x.startswith(lo):
                    y = _swap(x, lo, n.lower(), direct_only)
                    if y != x:
                        return y
        return x

    def walk(v):
        if isinstance(v, str):
            return s(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {(s(k) if isinstance(k, str) else k): walk(x) for k, x in v.items()}
        return v
    return walk(obj)


SKIP_FILES = {"config.json", "token.json"}  # config se guarda aparte (está en memoria)


def rewrite_support(prefixes, exact=None):
    """Aplica rewrite a los archivos de datos de BrainOrder (cachés, foto de Rekordbox, Historial…)."""
    changed = []
    files = [p for p in SUPPORT_DIR.glob("*.json") if p.name not in SKIP_FILES]
    hist = SUPPORT_DIR / "historial"
    if hist.is_dir():
        files += list(hist.glob("*.json"))
    for p in files:
        try:
            raw = p.read_text("utf-8")
            if not any(o in raw for o in prefixes) and not any(k in raw for k in exact or {}):
                continue
            data = json.loads(raw)
            new = rewrite(data, prefixes, exact)
            if new != data:
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(new, ensure_ascii=False), "utf-8")
                os.replace(tmp, p)
                changed.append(p.name)
        except Exception as e:
            log(f"corregir rutas en {p.name}: {e!r}")
    return changed


def file_map(old_root, new_root):
    """{ruta vieja: ruta nueva} de todos los archivos que ahora están en new_root (para corregir los
    programas de DJ, que guardan la ruta de cada canción)."""
    out = {}
    new_root, old_root = Path(new_root), Path(old_root)
    for d, ds, fs in os.walk(new_root):
        ds[:] = [x for x in ds if not x.startswith(".")]
        for f in fs:
            if f.startswith("."):
                continue
            p = Path(d) / f
            out[str(old_root / p.relative_to(new_root))] = str(p)
    return out
