"""Reglas que cada usuario ajusta a su gusto (pantalla «Reglas»).

- Exclusiones: carpetas y patrones que BrainOrder nunca lee, mueve ni cuenta.
- Prioridad de playlists: la primera de la lista donde aparece una canción es su carpeta «hogar».
- Modo por playlist: «organizar» (normal) o «ignorar» (no se analiza, no tiene carpeta, no toca Rekordbox).
- Comparación: tolerancia de duración y formato preferido cuando hay copias repetidas.
"""
import fnmatch
import os
import re
from pathlib import Path, PurePath

DEFAULTS = {
    "exclude_dirs": [],          # rutas completas: no se entra nunca
    "exclude_patterns": [],      # "Samples", "*stem*", "*.wav", "*/Sets grabados/*"
    "min_seconds": 0,            # audios más cortos se ignoran (samples, one-shots). 0 = desactivado
    "dur_tol_s": 6.0,            # misma grabación si la duración difiere hasta X segundos…
    "dur_tol_pct": 3.0,          # …o hasta X % (lo que sea mayor)
    "format_order": ["aiff", "wav", "flac", "m4a", "mp3"],  # cuál se queda cuando hay repetidos
    "playlist_order": [],        # ids en orden de prioridad (las que no estén van después)
    "playlist_mode": {},         # id -> "organizar" | "ignorar"
}

FORMATS = ["aiff", "wav", "flac", "alac", "m4a", "aac", "mp3", "ogg"]
_ALIAS = {"aif": "aiff", "mp4": "m4a"}


def get(cfg):
    r = dict(DEFAULTS)
    r.update({k: v for k, v in (cfg.get("rules") or {}).items() if k in DEFAULTS})
    return r


def clean(rules):
    """Valida lo que llega de la pantalla. Devuelve (reglas, errores)."""
    r, errs = dict(DEFAULTS), []
    dirs = []
    for d in rules.get("exclude_dirs") or []:
        d = str(d).strip()
        if d and d not in dirs:
            dirs.append(d)
    r["exclude_dirs"] = dirs
    pats = []
    for p in rules.get("exclude_patterns") or []:
        p = str(p).strip()
        if p and p not in pats:
            if p in ("*", "*.*", "**"):
                errs.append(f"El patrón «{p}» excluiría toda tu música.")
                continue
            pats.append(p)
    r["exclude_patterns"] = pats

    def num(key, lo, hi):
        try:
            v = float(rules.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            errs.append(f"{key}: no es un número.")
            return DEFAULTS[key]
        return max(lo, min(hi, v))
    r["min_seconds"] = num("min_seconds", 0, 600)
    r["dur_tol_s"] = num("dur_tol_s", 0, 60)
    r["dur_tol_pct"] = num("dur_tol_pct", 0, 20)
    order = [f for f in (rules.get("format_order") or []) if f in FORMATS]
    r["format_order"] = order + [f for f in DEFAULTS["format_order"] if f not in order]
    r["playlist_order"] = [str(x) for x in rules.get("playlist_order") or []]
    r["playlist_mode"] = {str(k): v for k, v in (rules.get("playlist_mode") or {}).items()
                          if v in ("organizar", "ignorar")}
    return r, errs


# ---------------------------------------------------------------- exclusiones
class Excluder:
    """Decide si una carpeta o archivo queda fuera. Sin distinguir mayúsculas.

    Patrones:
      Samples            -> cualquier carpeta llamada así (o archivo con ese nombre exacto)
      *stem*             -> nombre de carpeta o archivo que contenga «stem»
      *.wav              -> por extensión
      */Sets grabados/*  -> con «/»: se compara con la ruta completa
    """

    def __init__(self, rules):
        self.dirs = [os.path.normcase(os.path.normpath(d)) for d in rules.get("exclude_dirs") or []]
        self.name_pats, self.path_pats = [], []
        for p in rules.get("exclude_patterns") or []:
            p = p.replace("\\", "/").strip()
            if "/" in p:
                self.path_pats.append(re.compile(fnmatch.translate(p.lower())))
            else:
                self.name_pats.append(re.compile(fnmatch.translate(p.lower())))
        self.min_seconds = float(rules.get("min_seconds") or 0)

    def __bool__(self):
        return bool(self.dirs or self.name_pats or self.path_pats or self.min_seconds)

    def _under(self, path):
        p = os.path.normcase(os.path.normpath(path))
        return any(p == d or p.startswith(d + os.sep) for d in self.dirs)

    def _path_match(self, path):
        s = str(path).replace("\\", "/").lower()
        return any(rx.match(s) or rx.match(s + "/") for rx in self.path_pats)

    def dir_excluded(self, path):
        name = PurePath(path).name.lower()
        return self._under(path) or any(rx.match(name) for rx in self.name_pats) or self._path_match(path)

    def file_excluded(self, path, duration=None):
        """duration: función ruta -> segundos (solo se usa si hay mínimo de duración)."""
        name = PurePath(path).name.lower()
        if self._under(path) or any(rx.match(name) for rx in self.name_pats) or self._path_match(path):
            return True
        if self.min_seconds and duration:
            d = duration(str(path))
            if d is not None and d < self.min_seconds:
                return True
        return False


# ---------------------------------------------------------------- prioridades
def ordered_playlists(playlists, rules):
    """Playlists en orden de prioridad para elegir la carpeta hogar.
    Primero las que el usuario ordenó; luego las nuevas en el orden de Spotify; Me gusta al final
    salvo que el usuario la haya ubicado."""
    order = {pid: i for i, pid in enumerate(rules.get("playlist_order") or [])}
    n = len(order)

    def key(ip):
        i, p = ip
        if p["id"] in order:
            return (order[p["id"]], 0)
        return (n + (10_000 if p.get("liked") or p["id"] == "liked" else 0) + i, 0)
    return [p for _, p in sorted(enumerate(playlists), key=key)]


def ignored(rules, pid):
    return (rules.get("playlist_mode") or {}).get(pid) == "ignorar"


# ---------------------------------------------------------------- calidad
def quality(path, rules):
    """Menor = preferido. Formatos fuera de la lista van al final."""
    ext = Path(path).suffix.lower().lstrip(".")
    ext = _ALIAS.get(ext, ext)
    order = rules.get("format_order") or DEFAULTS["format_order"]
    return order.index(ext) if ext in order else len(order)
