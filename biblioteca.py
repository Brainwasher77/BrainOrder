"""Escaneo de la música local y cruce con Spotify."""
import difflib
import json
import threading
import os
import re
import unicodedata
from pathlib import Path

from config import AUDIO_EXT, safe_name

try:
    import mutagen  # opcional: solo para archivos sin "Artista - Título" en el nombre
except Exception:  # pragma: no cover
    mutagen = None

# Palabras que no cambian la versión de una canción
NOISE = {"remaster", "remastered", "remasterizado", "remasterizada", "version", "versión", "original",
         "explicit", "clean", "mono", "stereo", "single", "album", "edition", "deluxe", "radio",
         "feat", "ft", "featuring", "with", "con", "prod", "by", "the", "and", "y", "of", "de"}
# Palabras que SÍ indican otra versión
VERSIONY = {"remix", "rmx", "mix", "edit", "live", "en", "vivo", "acoustic", "acustico", "vip",
            "bootleg", "dub", "instrumental", "acapella", "acap", "extended", "rework", "flip",
            "cover", "sped", "slowed", "club"}
UNKNOWN_ARTISTS = {"", "desconocido", "unknown", "unknown artist", "artista desconocido", "various artists", "va"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("$", "s")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_feat(t: str) -> str:
    return re.sub(r"\s*[\(\[]\s*(feat|ft|with|con)\b.*?[\)\]]", "", t, flags=re.I)


def core_title(t: str) -> str:
    t = _strip_feat(t)
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", t)
    t = re.split(r"\s+[-–]\s+", t)[0]
    t = re.sub(r"\s+(feat|ft)\.?\s.*$", "", t, flags=re.I)
    return norm(t)


SAME_VERSION = re.compile(r"\b(radio\s+edit|radio\s+version|radio\s+mix|short\s+edit|single\s+(edit|version)|"
                          r"album\s+version|original\s+mix|clean\s+edit|\d+[\W_]*\s*edit)\b", re.I)


def extras(t: str) -> frozenset:
    """Palabras de versión (remix, edit…) que tiene el título además del núcleo."""
    t = SAME_VERSION.sub(" ", _strip_feat(t))
    core = set(core_title(t).split())
    words = set(norm(t).split()) - core
    words = {w for w in words if w not in NOISE}
    return frozenset(words)


def version_diff(a: frozenset, b: frozenset) -> bool:
    """True si las palabras de versión indican grabaciones distintas (remix vs. no, Mix 1 vs Mix 2…).
    Los años (2005 Remaster) no cuentan."""
    d = a ^ b
    return bool(d & VERSIONY) or any(w.isdigit() and len(w) < 4 for w in d)


# ---------------- duración real de los archivos (con caché) ----------------
_DUR = {}
_DUR_FILE = [None]
_DUR_DIRTY = [False]


def load_durations(path):
    _DUR_FILE[0] = Path(path)
    try:
        _DUR.update(json.loads(Path(path).read_text("utf-8")))
    except Exception:
        pass


_DUR_LOCK = threading.Lock()


def save_durations():
    if _DUR_FILE[0] and _DUR_DIRTY[0]:
        with _DUR_LOCK:
            try:
                data = json.dumps(dict(_DUR))
                tmp = _DUR_FILE[0].with_name(f".{_DUR_FILE[0].name}.tmp")
                tmp.write_text(data, "utf-8")
                os.replace(tmp, _DUR_FILE[0])
                _DUR_DIRTY[0] = False
            except Exception:
                pass


def duration(path: str):
    """Duración en segundos (None si no se puede leer). Cacheada por ruta+tamaño+fecha."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{st.st_size}:{int(st.st_mtime)}"
    c = _DUR.get(path)
    if c and c[0] == key:
        return c[1]
    d = None
    if mutagen:
        try:
            m = mutagen.File(path)
            if m and m.info and m.info.length:
                d = round(float(m.info.length), 1)
        except Exception:
            d = None
    _DUR[path] = [key, d]
    _DUR_DIRTY[0] = True
    return d


def same_length(a, b):
    """Duraciones compatibles: misma grabación (tolerancia max(6 s, 3 %))."""
    if a is None or b is None:
        return True
    return abs(a - b) <= max(6.0, 0.03 * max(a, b))


# ---------------- carpetas con nombre equivalente ----------------
def folder_key(name: str) -> str:
    """'Stay High🌒' == 'Stay High', 'Clásica' == 'Clasica', "Gangsta's" == 'Gangstas'."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", n)


def _audio_count(d: Path) -> int:
    try:
        return sum(1 for f in os.scandir(d) if f.is_file() and Path(f.name).suffix.lower() in AUDIO_EXT)
    except OSError:
        return 0


def similar_folders(a: str, b: str) -> bool:
    ka, kb = folder_key(a), folder_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    return min(len(ka), len(kb)) >= 10 and difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.92


def resolve_folder(dest_root: Path, playlist_name: str, _cache={}) -> Path:
    """Carpeta que corresponde a la playlist: si ya existe una con nombre equivalente
    (con/sin emoji, tildes o apóstrofes), usa la que más música tenga."""
    exact = dest_root / safe_name(playlist_name)
    try:
        subdirs = [d for d in dest_root.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]
    except OSError:
        return exact
    same = [d for d in subdirs if similar_folders(d.name, playlist_name)]
    if not same:
        return exact
    best = max(same, key=lambda d: (_audio_count(d), d == exact))
    if _audio_count(best) == 0 and exact.exists():
        return exact
    return best


def artist_ok(sp_artists, file_artist_norm: str) -> bool:
    if file_artist_norm in UNKNOWN_ARTISTS:
        return False
    for a in sp_artists:
        an = norm(a)
        if len(an) >= 2 and (an in file_artist_norm or file_artist_norm in an):
            return True
    return False


class LocalFile:
    __slots__ = ("path", "artist", "title", "core", "extras", "artist_n", "dir")

    def __init__(self, path: Path, artist: str, title: str):
        self.path = str(path)
        self.dir = str(path.parent)
        self.artist = artist
        self.title = title
        self.core = core_title(title)
        self.extras = extras(title)
        self.artist_n = norm(artist)


def parse_file(p: Path):
    stem = p.stem
    stem = re.sub(r"\s*\(\d+\)$", "", stem)  # "Canción (2)" -> copia duplicada
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        artist, title = artist.strip(), title.strip()
        if not re.fullmatch(r"\d{1,3}", artist):
            return artist, title
        # "01 - Canción.mp3" (álbum/EP): el número es la pista, no el artista
        tag_a = ""
        if mutagen:
            try:
                f = mutagen.File(str(p), easy=True)
                if f and f.tags:
                    tag_a = (f.tags.get("artist") or [""])[0]
                    title = (f.tags.get("title") or [title])[0] or title
            except Exception:
                pass
        folder = p.parent.name
        return (tag_a or (folder.split(" - ", 1)[0].strip() if " - " in folder else "")), title
    if mutagen:
        try:
            f = mutagen.File(str(p), easy=True)
            if f and f.tags:
                a = (f.tags.get("artist") or [""])[0]
                t = (f.tags.get("title") or [""])[0]
                if t:
                    return a, t
        except Exception:
            pass
    return "", stem


def scan(roots, progress=None):
    files = []
    seen = set()
    roots = list(roots)
    for ri, root in enumerate(roots):
        root = Path(root)
        if not root.exists():
            continue
        if progress:
            progress(f"Revisando tus carpetas: {root.name}…", 0.35 * ri / max(1, len(roots)))
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                p = Path(dirpath) / fn
                if p.suffix.lower() not in AUDIO_EXT:
                    continue
                key = str(p)
                if key in seen:
                    continue
                seen.add(key)
                a, t = parse_file(p)
                files.append(LocalFile(p, a, t))
    return files


class Index:
    def __init__(self, files):
        self.by_core = {}
        for f in files:
            self.by_core.setdefault(f.core, []).append(f)
        self.cores = list(self.by_core)

    def find(self, track):
        """Todas las copias locales que corresponden al track de Spotify."""
        core = core_title(track["name"])
        ex = extras(track["name"])
        cands = list(self.by_core.get(core, []))
        if not cands and len(core) >= 4:
            for c in difflib.get_close_matches(core, self.cores, n=3, cutoff=0.9):
                cands += self.by_core[c]
        out = []
        self.last_extras = ex
        tdur = (track.get("duration_ms") or 0) / 1000 or None
        for f in cands:
            if not artist_ok(track["artists"], f.artist_n):
                # nombre sin artista: aceptar solo si el título completo coincide exacto
                if not (f.artist_n in UNKNOWN_ARTISTS and norm(f.title) == norm(track["name"])):
                    continue
            fx = f.extras
            if (ex <= fx or fx <= ex) and not version_diff(ex, fx):
                # si cambian palabras como "radio edit"/"original mix", confirmar con la duración
                if tdur and (ex != fx or len(cands) > 1) and not same_length(tdur, duration(f.path)):
                    continue
                out.append(f)
        return out


def _rank(f: LocalFile):
    ext = Path(f.path).suffix.lower()
    q = {".aif": 0, ".aiff": 0, ".wav": 0, ".flac": 1, ".m4a": 2, ".mp3": 3}.get(ext, 4)
    try:
        size = -os.path.getsize(f.path)
    except OSError:
        size = 0
    return (q, size)


def analyze(playlists, cfg, progress=None):
    """Cruza playlists de Spotify con los archivos locales, sin duplicar archivos.

    Cada canción tiene UN solo archivo. Su carpeta "hogar" es la de la primera playlist
    donde aparece (Me gusta va de última). Estados por fila:
      ok         -> el archivo está en su carpeta hogar
      elsewhere  -> ya lo tienes en otra carpeta; se usa ahí, no se copia
      inbox      -> está en descargas; Organizar lo MUEVE a su carpeta hogar
      missing    -> falta por descargar
    inbox_dups: descargas que repiten una canción que ya tienes (van a _duplicados).
    """
    dest_root = Path(cfg["dest_root"])
    inbox = Path(cfg["inbox"])
    roots = [dest_root, inbox] + [Path(r) for r in cfg.get("library_roots", [])]
    skip = {str(inbox / cfg.get("inbox_done", "_organizadas")), str(inbox / "_duplicados"),
            str(dest_root / "_duplicados"), str(dest_root / "_Informes")}
    files = [f for f in scan(roots, progress) if not any(f.path.startswith(s + os.sep) for s in skip)]
    if progress:
        progress(f"{len(files)} archivos locales. Cruzando con Spotify…", 0.35)
    total_tracks = sum(len(p["tracks"]) for p in playlists) or 1
    done_tracks = 0
    idx = Index(files)
    inbox_s = str(inbox) + os.sep
    dest_s = str(dest_root) + os.sep

    # carpeta hogar de cada canción: primera playlist (Me gusta al final)
    ordered = [p for p in playlists if not p.get("liked")] + [p for p in playlists if p.get("liked")]
    folders = {pl["id"]: str(resolve_folder(dest_root, pl["name"])) for pl in playlists}
    home, home_name = {}, {}
    for pl in ordered:
        folder = folders[pl["id"]]
        for t in pl["tracks"]:
            if t["id"] not in home:
                home[t["id"]], home_name[t["id"]] = folder, pl["name"]

    out = []
    for pl in playlists:
        folder_s = folders[pl["id"]]
        rows = []
        for pos, t in enumerate(pl["tracks"]):
            done_tracks += 1
            if progress and done_tracks % 20 == 0:
                progress(f"Cruzando canciones: {done_tracks}/{total_tracks}", 0.35 + 0.65 * done_tracks / total_tracks)
            matches = idx.find(t)
            ex = extras(t["name"])
            rank = lambda f, ex=ex: (f.extras != ex, not f.path.startswith(dest_s)) + _rank(f)
            hdir = home[t["id"]]
            in_inbox = [m for m in matches if m.path.startswith(inbox_s)]
            owned = [m for m in matches if m not in in_inbox]
            in_home = [m for m in owned if m.dir == hdir]
            dups = []
            if in_home:
                status, src = "ok", sorted(in_home, key=rank)[0]
                dups = in_inbox
            elif owned:
                status, src = "elsewhere", sorted(owned, key=rank)[0]
                dups = in_inbox
            elif in_inbox:
                ordered_in = sorted(in_inbox, key=rank)
                status, src = "inbox", ordered_in[0]
                dups = ordered_in[1:]
            else:
                status, src = "missing", None
            rows.append({
                "pos": pos,
                "id": t["id"],
                "name": t["name"],
                "artists": t["artists"],
                "album": t.get("album", ""),
                "url": t.get("url", ""),
                "isrc": t.get("isrc", ""),
                "status": status,
                "source": src.path if src else None,
                "dest_dir": hdir,
                "home_name": home_name[t["id"]],
                "inbox_dups": [d.path for d in dups],
            })
        out.append({"id": pl["id"], "name": pl["name"], "folder": folder_s, "tracks": rows,
                    "liked": pl.get("liked", False)})
    save_durations()
    return out
