"""Carpetas de ACCESOS DIRECTOS (por ejemplo «Playlists rekordbox»): no tienen música propia, solo apuntan a
canciones que ya están en tu carpeta de playlists. Tenerlas como carpeta de música hacía que salieran como
«Playlists nuevas» repetidas.

scan(folder)  -> qué hay: accesos directos (con su archivo real), rotos, música real, otros archivos.
Quitar (app.shortcuts_remove):
  1) Rekordbox y tus otros programas: las pistas que apuntaban al acceso directo pasan a apuntar al archivo
     real (si el archivo real ya estaba en la colección, se UNEN y se conservan cues). Rekordbox cerrado y
     con respaldo.
  2) La música real que hubiera ahí se muda a «_Sin Playlist» de tu carpeta de playlists (nunca se borra).
  3) Los accesos directos van a la Papelera (se pueden recuperar) y la carpeta sale de tus carpetas de música.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import AUDIO_EXT, log

ALIAS_MAGIC = b"book\x00\x00\x00\x00mark"
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized", "Icon\r"}


def is_alias(p):
    """Alias de Finder (no es un symlink: es un archivo chico que guarda a dónde apunta)."""
    try:
        if os.path.islink(p) or os.path.getsize(p) > 1_000_000:
            return False
        with open(p, "rb") as f:
            return f.read(len(ALIAS_MAGIC)) == ALIAS_MAGIC
    except OSError:
        return False


def _alias_target(p, by_name):
    """Un alias no se puede leer sin las librerías de macOS: se busca un archivo real con el mismo nombre
    (sin « alias») y solo si hay UNO."""
    name = Path(p).name
    for suf in (" alias", " Alias", " - alias"):
        if name.endswith(suf):
            name = name[: -len(suf)]
    hits = by_name.get(name.casefold()) or []
    return hits[0] if len(hits) == 1 else None


def scan(folder, music_roots=()):
    """-> {"links": {acceso: real}, "broken": [accesos rotos], "audio": [música real], "other": [otros],
           "share": proporción de accesos directos entre lo que tiene}"""
    folder = Path(folder)
    out = {"links": {}, "broken": [], "audio": [], "other": [], "aliases_unknown": []}
    aliases = []
    for d, ds, fs in os.walk(folder):
        ds[:] = [x for x in ds if not x.startswith(".")]
        for f in fs:
            p = os.path.join(d, f)
            if f in JUNK or f.startswith("._"):
                continue
            if os.path.islink(p):
                real = os.path.realpath(p)
                if os.path.isfile(real):
                    out["links"][p] = real
                else:
                    out["broken"].append(p)
            elif is_alias(p):
                aliases.append(p)
            elif os.path.splitext(f)[1].lower() in AUDIO_EXT:
                out["audio"].append(p)
            else:
                out["other"].append(p)
    if aliases:
        by_name = {}
        for r in music_roots:
            if not r or not os.path.isdir(r) or os.path.normcase(str(r)) == os.path.normcase(str(folder)):
                continue
            for d, ds, fs in os.walk(r):
                ds[:] = [x for x in ds if not x.startswith(".")]
                for f in fs:
                    if os.path.splitext(f)[1].lower() in AUDIO_EXT and not os.path.islink(os.path.join(d, f)):
                        by_name.setdefault(f.casefold(), []).append(os.path.join(d, f))
        for a in aliases:
            t = _alias_target(a, by_name)
            if t:
                out["links"][a] = t
            else:
                out["aliases_unknown"].append(a)
    n_links = len(out["links"]) + len(out["broken"]) + len(out["aliases_unknown"])
    total = n_links + len(out["audio"])
    out["share"] = (n_links / total) if total else 0.0
    return out


def looks_like_shortcuts(folder, music_roots=(), min_share=0.7):
    s = scan(folder, music_roots)
    return s if (s["links"] or s["broken"]) and s["share"] >= min_share else None


def to_trash(paths, label="Accesos directos"):
    """Manda a la Papelera (se puede recuperar). -> [(ruta, dónde quedó)]"""
    out = []
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M")
    for p in paths:
        p = Path(p)
        if not (p.exists() or os.path.islink(p)):
            continue
        if sys.platform == "darwin" or sys.platform.startswith("linux"):
            base = Path.home() / ".Trash" if sys.platform == "darwin" else Path.home() / ".local/share/Trash/files"
            base.mkdir(parents=True, exist_ok=True)
            dest = base / p.name
            n = 2
            while dest.exists() or os.path.islink(dest):
                dest = base / f"{p.name} ({stamp}{'' if n == 2 else ' ' + str(n)})"
                n += 1
            shutil.move(str(p), str(dest))
            out.append((str(p), str(dest)))
        else:
            kind = "DeleteDirectory" if p.is_dir() and not os.path.islink(p) else "DeleteFile"
            ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::"
                  f"{kind}('{str(p).replace(chr(39), chr(39) * 2)}','OnlyErrorDialogs','SendToRecycleBin')")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out.append((str(p), "Papelera de reciclaje"))
    if label:
        log(f"{label} a la Papelera: {len(out)}")
    return out
