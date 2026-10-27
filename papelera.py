"""Buscar en la papelera canciones que te faltan (perdidas en Rekordbox o «faltan por descargar»).

Dónde mira:
  - macOS: ~/.Trash y la papelera de cada disco externo (/Volumes/<disco>/.Trashes/<tu usuario>).
    macOS solo deja leer la papelera a las apps con «Acceso total al disco».
  - Windows: X:\\$Recycle.Bin\\<tu usuario>\\ en cada disco. Los archivos ahí se llaman $Rxxxx; su nombre y
    su ruta original están en el $Ixxxx de al lado.
  - Linux: ~/.local/share/Trash/files.
Solo lee. Recuperar mueve el archivo de la papelera a su lugar (con Historial para deshacer).
"""
import os
import struct
import sys
from pathlib import Path

import rb_perdidas as RP

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


class TrashError(Exception):
    pass


def trash_dirs():
    out = []
    home = Path.home()
    if IS_MAC:
        out.append(home / ".Trash")
        vols = Path("/Volumes")
        if vols.is_dir():
            try:
                for v in vols.iterdir():
                    t = v / ".Trashes" / str(os.getuid())
                    if t.is_dir():
                        out.append(t)
            except OSError:
                pass
    elif IS_WIN:
        import string
        for letter in string.ascii_uppercase:
            rb = Path(f"{letter}:\\$Recycle.Bin")
            try:
                if not rb.is_dir():
                    continue
                for sid in rb.iterdir():  # solo se puede abrir la del usuario actual; las demás dan error
                    try:
                        if sid.is_dir() and os.access(sid, os.R_OK):
                            out.append(sid)
                    except OSError:
                        pass
            except OSError:
                pass
    else:
        out.append(home / ".local" / "share" / "Trash" / "files")
    return out


def _win_original(ipath):
    """Ruta original de un archivo de la papelera de Windows (desde su $I)."""
    try:
        data = Path(ipath).read_bytes()
        ver = struct.unpack_from("<q", data, 0)[0]
        if ver == 2:
            n = struct.unpack_from("<i", data, 24)[0]
            return data[28:28 + n * 2].decode("utf-16-le").rstrip("\x00")
        return data[24:24 + 520].decode("utf-16-le").split("\x00", 1)[0]
    except Exception:
        return None


def list_audio():
    """Audios en la papelera -> [{path, name, size, original}]. Lanza TrashError si no se puede leer."""
    out, denied = [], []
    for root in trash_dirs():
        try:
            entries = list(os.scandir(root))
        except PermissionError:
            denied.append(str(root))
            continue
        except OSError:
            continue
        for e in entries:
            original = None
            if IS_WIN and e.name.upper().startswith("$R"):
                original = _win_original(Path(root) / ("$I" + e.name[2:]))
            if e.is_dir(follow_symlinks=False):
                for d, ds, fs in os.walk(e.path):
                    ds[:] = [x for x in ds if not x.startswith(".")]
                    for f in fs:
                        if f.lower().endswith(RP.AUDIO) and not f.startswith("._"):
                            p = os.path.join(d, f)
                            orig = os.path.join(original, os.path.relpath(p, e.path)) if original else None
                            _add(out, p, f, orig)
            elif e.name.lower().endswith(RP.AUDIO) and not e.name.startswith("._"):
                name = os.path.basename(original) if original else e.name
                _add(out, e.path, name, original)
    if denied and not out:
        msg = "No tengo permiso para leer la papelera."
        if IS_MAC:
            msg += (" En el Mac: Ajustes del Sistema → Privacidad y seguridad → Acceso total al disco → activa BrainOrder"
                    " (si no aparece, agrégalo con «+» desde Aplicaciones) y vuelve a intentar.")
        raise TrashError(msg)
    return out


# carpetas de programas y de BrainOrder que no son descargas sueltas
_NOT_LOOSE = {"ableton", "audio music apps", "music", "pioneerdj", "traktor", "_serato_", "_serato_backup", "djay",
              "rekordbox", "mapeos", "xml´s", "xml's", "itunes", "garageband", "logic"}


def outside_dirs(cfg):
    """Carpetas donde suelen quedar descargas y que BrainOrder no revisa: Descargas, Escritorio y las
    carpetas de tu carpeta de Música que no están en Ajustes."""
    home = Path.home()
    known = [cfg.get("dest_root"), cfg.get("inbox")] + list(cfg.get("library_roots") or [])
    known = [os.path.normcase(os.path.abspath(k)) for k in known if k]

    def inside_known(p):
        q = os.path.normcase(os.path.abspath(str(p)))
        return any(q == k or q.startswith(k.rstrip(os.sep) + os.sep) or k.startswith(q.rstrip(os.sep) + os.sep)
                   for k in known)
    out = [home / "Downloads", home / "Desktop"]
    for base in (home / "Music", home / "Música"):
        try:
            for d in base.iterdir():
                if d.is_dir() and not d.name.startswith(".") and d.name.lower() not in _NOT_LOOSE:
                    out.append(d)
        except OSError:
            pass
    return [d for d in out if d.is_dir() and not inside_known(d)]


def list_audio_dirs(dirs, limit=200000):
    """Audios en esas carpetas (sin leer las de permiso denegado)."""
    out = []
    for root in dirs:
        try:
            for d, ds, fs in os.walk(root):
                ds[:] = [x for x in ds if not x.startswith(".") and x != "_duplicados"]
                for f in fs:
                    if f.lower().endswith(RP.AUDIO) and not f.startswith("._"):
                        _add(out, os.path.join(d, f), f, None)
                        if len(out) >= limit:
                            return out
        except OSError:
            continue
    return out


def _add(out, path, name, original):
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    out.append({"path": path, "name": name, "size": size, "original": original, "stem": RP.norm_stem(name)})


def match(trash, lost=(), missing=(), duration=None):
    """Cruza la papelera con lo que te falta.
    lost: items de rb_perdidas.scan (state «lost»). missing: [{id, name, artists, dest_dir, playlists}].
    -> [{trash, name, size, kind: «rb»|«faltan», target, title, artist, pls, why}]"""
    by_stem, by_name = {}, {}
    for t in trash:
        by_stem.setdefault(t["stem"], []).append(t)
        by_name.setdefault(t["name"].lower(), []).append(t)
    used, out = set(), []

    def pick(cands, size=None, secs=None):
        for t in cands:
            if t["path"] in used:
                continue
            if size and t["size"] == size:
                return t, "el mismo archivo"
        for t in cands:
            if t["path"] in used:
                continue
            if secs and duration:
                d = duration(t["path"])
                if d and abs(d - secs) <= RP.TOL:
                    return t, "mismo nombre y duración"
            elif not secs:
                return t, "mismo nombre"
        return None, None

    for x in lost:
        if x.get("state") != "lost":
            continue
        name = os.path.basename(x["path"])
        cands = by_name.get(name.lower(), []) + [t for t in by_stem.get(RP.norm_stem(name), [])
                                                   if t["name"].lower() != name.lower()]
        t, why = pick(cands, x.get("size"), x.get("len"))
        if t:
            used.add(t["path"])
            out.append({"trash": t["path"], "name": t["name"], "size": t["size"], "kind": "rb", "id": x["id"],
                        "target": x["path"], "title": x["title"], "artist": x["artist"], "pls": x.get("pls") or [],
                        "why": why})
    for m in missing:
        arts = [a for a in (m.get("artists") or []) if a]
        artist = arts[0] if arts else ""
        keys = [RP.norm_stem(m["name"] + ".x")]
        for a in ([artist, ", ".join(arts), " & ".join(arts)] if arts else []):
            keys.insert(0, RP.norm_stem(f"{a} - {m['name']}.x"))
        cands = []
        for k in dict.fromkeys(keys):
            cands += [t for t in by_stem.get(k, []) if t not in cands]
        secs = (m.get("duration_ms") or 0) / 1000 or None
        t, why = pick(cands, None, secs)
        if t:
            used.add(t["path"])
            out.append({"trash": t["path"], "name": t["name"], "size": t["size"], "kind": "faltan", "id": m["id"],
                        "target": os.path.join(m["dest_dir"], t["name"]), "title": m["name"], "artist": artist,
                        "pls": m.get("playlists") or [], "why": why})
    return out
