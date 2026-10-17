"""Serato DJ como destino: crea un crate por playlist dentro de un crate padre.

Formato (binario, big-endian): campos [4 letras][largo uint32][datos]; textos en UTF-16BE.
  vrsn  "1.0/Serato ScratchLive Crate"
  otrk  { ptrk "Users/frank/Music/x.mp3" }   <- ruta relativa a la raíz del disco, con "/"
Subcrates: _Serato_/Subcrates/<Padre>%%<Hijo>.crate
Cada disco tiene su propia carpeta _Serato_ (la del disco principal está en ~/Music/_Serato_).

- Serato tiene que estar cerrado.
- Antes de escribir se copian los crates que se van a cambiar a _Serato_/BrainOrder respaldos/.
- Si BrainOrder mueve archivos, corrige las rutas en los crates y en «database V2».
"""
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import log

KEY = "serato"
LABEL = "Serato DJ"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
VERSION = "1.0/Serato ScratchLive Crate"
COLUMNS = ["song", "artist", "bpm", "key", "album", "length", "added"]


class SeratoError(Exception):
    pass


# ---------------------------------------------------------------- binario
def _tlv(tag, data):
    return struct.pack(">4sI", tag.encode("ascii"), len(data)) + data


def _txt(s):
    return s.encode("utf-16-be")


def parse(data):
    """-> [(tag, bytes)] del nivel superior."""
    out, i = [], 0
    while i + 8 <= len(data):
        tag, n = struct.unpack(">4sI", data[i:i + 8])
        out.append((tag.decode("ascii", "replace"), data[i + 8:i + 8 + n]))
        i += 8 + n
    return out


def dump(entries):
    return b"".join(_tlv(t, d) for t, d in entries)


def build_crate(relpaths):
    body = [("vrsn", _txt(VERSION)),
            ("osrt", _tlv("tvcn", _txt("song")) + _tlv("brev", b"\x00"))]
    body += [("ovct", _tlv("tvcn", _txt(c)) + _tlv("tvcw", _txt("0"))) for c in COLUMNS]
    body += [("otrk", _tlv("ptrk", _txt(p))) for p in relpaths]
    return dump(body)


def crate_tracks(data):
    out = []
    for tag, d in parse(data):
        if tag == "otrk":
            for t2, d2 in parse(d):
                if t2 == "ptrk":
                    out.append(d2.decode("utf-16-be", "replace"))
    return out


def _rewrite_paths(data, field, mapping, dedupe=False):
    """Cambia rutas (ptrk en crates, pfil en database V2) según mapping {vieja_rel: nueva_rel}.
    dedupe: en crates, si dos entradas quedan apuntando al mismo archivo se deja una sola."""
    changed, out, seen = 0, [], set()
    for tag, d in parse(data):
        if tag == "otrk":
            sub, path = [], None
            for t2, d2 in parse(d):
                if t2 == field:
                    p = d2.decode("utf-16-be", "replace")
                    if p in mapping:
                        p = mapping[p]
                        d2 = _txt(p)
                        changed += 1
                    path = p
                sub.append((t2, d2))
            if dedupe and path is not None:
                if path in seen:
                    changed += 1
                    continue
                seen.add(path)
            d = dump(sub)
        out.append((tag, d))
    return dump(out), changed


# ---------------------------------------------------------------- rutas y discos
def _volume_of(path):
    """-> (raíz del disco, ruta relativa a esa raíz con «/»)."""
    p = str(path)
    if IS_WIN or re.match(r"^[A-Za-z]:[\\/]", p):
        drive, rest = os.path.splitdrive(p)
        return drive + "\\", rest.replace("\\", "/").lstrip("/")
    parts = Path(p).parts
    if len(parts) > 3 and parts[1] == "Volumes":
        return str(Path("/", "Volumes", parts[2])), "/".join(parts[3:])
    return "/", p.lstrip("/")


def home_serato(cfg):
    s = ((cfg.get("destinations") or {}).get(KEY) or {}).get("dir")
    return Path(s) if s else Path.home() / "Music" / "_Serato_"


def _serato_dir_for(root, cfg):
    home = home_serato(cfg)
    if _volume_of(str(home))[0] == root:
        return home
    d = Path(root) / "_Serato_"
    return d if d.is_dir() else None


def available(cfg):
    return home_serato(cfg).is_dir()


def enabled(cfg):
    return bool(((cfg.get("destinations") or {}).get(KEY) or {}).get("enabled")) and available(cfg)


def running():
    try:
        if IS_MAC:
            out = subprocess.run(["ps", "-axo", "comm"], capture_output=True, text=True, timeout=5).stdout
            return any("Serato DJ" in l for l in out.splitlines())
        if IS_WIN:
            r = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "serato" in r.stdout.lower()
    except Exception:
        return False
    return False


def _crate_name(s):
    s = re.sub(r'[\\/:*?"<>|]', "-", s).replace("%%", "%").strip(" .")
    return s or "Playlist"


class _Backup:
    def __init__(self, serato_dir):
        self.dir = Path(serato_dir) / "BrainOrder respaldos" / f"{datetime.now():%Y%m%d-%H%M%S}"
        self.done = set()

    def save(self, f):
        f = Path(f)
        if not f.exists() or f in self.done:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, self.dir / f.name)
        self.done.add(f)
        root = self.dir.parent
        for old in sorted(p for p in root.iterdir() if p.is_dir())[:-5]:
            shutil.rmtree(old, ignore_errors=True)


def _write(path, data, backup):
    path = Path(path)
    if path.exists() and path.read_bytes() == data:
        return False
    backup.save(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return True


def sync(analysis, cfg, progress=None):
    if not available(cfg):
        raise SeratoError(f"No encontré la carpeta de Serato ({home_serato(cfg)}). Abre Serato una vez o elígela en Conexiones.")
    if running():
        raise SeratoError("Serato está abierto. Ciérralo y vuelve a intentarlo.")
    parent = _crate_name(cfg.get("rekordbox_folder") or "BrainOrder")
    backups = {}
    stats = {"playlists_updated": 0, "tracks_added": 0, "skipped_drives": 0}
    analysis = [p for p in analysis if not p.get("pending")]
    for i, pl in enumerate(analysis, 1):
        if progress:
            progress(f"Serato {i}/{len(analysis)}: {pl['name']}", i / max(1, len(analysis)))
        by_drive, seen = {}, set()
        for r in pl["tracks"]:
            if r["status"] in ("ok", "elsewhere") and r.get("source") and r["source"] not in seen:
                seen.add(r["source"])
                root, rel = _volume_of(r["source"])
                by_drive.setdefault(root, []).append(rel)
        home_root = _volume_of(str(home_serato(cfg)))[0]
        by_drive.setdefault(home_root, [])
        changed = False
        for root, rels in by_drive.items():
            sdir = _serato_dir_for(root, cfg)
            if sdir is None:
                stats["skipped_drives"] += len(rels)
                continue
            b = backups.setdefault(str(sdir), _Backup(sdir))
            sub = sdir / "Subcrates"
            _write(sub / f"{parent}.crate", build_crate([]), b)
            target = sub / f"{parent}%%{_crate_name(pl['name'])}.crate"
            if not rels and not target.exists():
                continue
            changed |= _write(target, build_crate(rels), b)
        stats["playlists_updated"] += changed
    log(f"Serato: {stats}")
    return stats


def fix_paths(cfg, moved, repoint=None):
    """Corrige rutas en los crates (y en database V2) de cada disco con carpeta _Serato_.
    moved: {vieja: nueva} el archivo cambió de lugar.
    repoint: {vieja: conservada} copia repetida apartada: los crates pasan a usar la conservada."""
    def rel_map(d):
        out = {}
        for old, new in (d or {}).items():
            ro, rel_o = _volume_of(old)
            rn, rel_n = _volume_of(new)
            if ro == rn:
                out.setdefault(ro, {})[rel_o] = rel_n
        return out
    mv, rp = rel_map(moved), rel_map(repoint)
    roots = set(mv) | set(rp)
    if not roots:
        return None
    if running():
        raise SeratoError("Serato está abierto. Ciérralo para corregir sus rutas.")
    n = 0
    for root in roots:
        sdir = _serato_dir_for(root, cfg)
        if sdir is None:
            continue
        b = _Backup(sdir)
        crate_map = {**mv.get(root, {}), **rp.get(root, {})}  # en playlists gana la copia conservada
        sub = sdir / "Subcrates"
        for f in (sub.glob("*.crate") if sub.is_dir() else []):
            data, c = _rewrite_paths(f.read_bytes(), "ptrk", crate_map, dedupe=True)
            if c:
                _write(f, data, b)
                n += c
        db = sdir / "database V2"
        if db.exists() and mv.get(root):
            data, c = _rewrite_paths(db.read_bytes(), "pfil", mv[root])
            if c:
                _write(db, data, b)
                n += c
    return {"refs": n, "backup": "BrainOrder respaldos"}
