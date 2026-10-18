"""Traktor Pro como destino: replica tus playlists en collection.nml.

- Traktor tiene que estar cerrado (al cerrarse reescribe su colección y borraría los cambios).
- Antes de tocar nada se respalda collection.nml (se guardan los 5 respaldos más recientes).
- Las canciones nuevas entran con título, artista y ruta; Traktor las analiza al abrirlas.
- Si BrainOrder mueve archivos (Reorganizar / Unificar), corrige sus rutas aquí también.
"""
import os
import re
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path, PureWindowsPath

from config import log

KEY = "traktor"
LABEL = "Traktor Pro"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


class TraktorError(Exception):
    pass


# ---------------------------------------------------------------- ubicación
def find_collection():
    """El collection.nml de la versión de Traktor más reciente."""
    base = Path.home() / "Documents" / "Native Instruments"
    try:
        cands = [d / "collection.nml" for d in base.iterdir() if d.name.lower().startswith("traktor")]
    except OSError:
        return None
    cands = [c for c in cands if c.exists()]
    return str(max(cands, key=lambda c: c.stat().st_mtime)) if cands else None


def nml_path(cfg):
    s = (cfg.get("destinations") or {}).get(KEY) or {}
    return s.get("nml") or find_collection()


def available(cfg):
    p = nml_path(cfg)
    return bool(p and Path(p).exists())


def enabled(cfg):
    return bool(((cfg.get("destinations") or {}).get(KEY) or {}).get("enabled")) and available(cfg)


def running():
    try:
        import plataforma
        if IS_MAC:
            return bool(plataforma.any_process(lambda l: "/Traktor" in l and ".app/" in l))
        if IS_WIN:
            return bool(plataforma.any_process(lambda l: "traktor" in l.lower()))
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- rutas al estilo Traktor
def _split(path, root_volume):
    """Ruta del sistema -> (VOLUME, DIR, FILE) como los guarda Traktor."""
    if IS_WIN or re.match(r"^[A-Za-z]:[\\/]", path):
        w = PureWindowsPath(path)
        vol = w.drive
        parts = list(w.parts[1:-1])
        return vol, "/:" + "".join(p + "/:" for p in parts), w.name
    parts = Path(path).parts
    if len(parts) > 2 and parts[1] == "Volumes":
        vol, rest = parts[2], parts[3:-1]
    else:
        vol, rest = root_volume, parts[1:-1]
    return vol, "/:" + "".join(p + "/:" for p in rest), parts[-1]


def _join(vol, d, f, root_volume):
    parts = [p for p in (d or "").split("/:") if p]
    if re.match(r"^[A-Za-z]:$", vol or ""):
        return str(PureWindowsPath(vol + "\\", *parts, f))
    if vol and vol != root_volume:
        return str(Path("/Volumes", vol, *parts, f))
    return str(Path("/", *parts, f))


def key_of(vol, d, f):
    return f"{vol}{d}{f}"


class Collection:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.tree = ET.parse(self.path)
        except ET.ParseError as e:
            raise TraktorError(f"No pude leer {self.path.name}: {e}")
        self.root = self.tree.getroot()
        self.coll = self.root.find("COLLECTION")
        if self.coll is None:
            self.coll = ET.SubElement(self.root, "COLLECTION", ENTRIES="0")
        self.by_key = {}
        vols = Counter()
        self.volid = {}
        for e in self.coll.findall("ENTRY"):
            loc = e.find("LOCATION")
            if loc is None:
                continue
            v, d, f = loc.get("VOLUME", ""), loc.get("DIR", ""), loc.get("FILE", "")
            self.by_key[key_of(v, d, f)] = e
            if d.startswith("/:Users/:"):
                vols[v] += 1
            if loc.get("VOLUMEID"):
                self.volid.setdefault(v, loc.get("VOLUMEID"))
        self.root_volume = vols.most_common(1)[0][0] if vols else ("C:" if IS_WIN else "Macintosh HD")

    def key(self, path):
        return key_of(*_split(path, self.root_volume))

    def ensure_entry(self, path, title, artist):
        k = self.key(path)
        if k in self.by_key:
            return k, False
        v, d, f = _split(path, self.root_volume)
        now = datetime.now()
        e = ET.SubElement(self.coll, "ENTRY", MODIFIED_DATE=f"{now.year}/{now.month}/{now.day}",
                          MODIFIED_TIME=str(now.hour * 3600 + now.minute * 60 + now.second),
                          TITLE=title or Path(path).stem, ARTIST=artist or "")
        ET.SubElement(e, "LOCATION", DIR=d, FILE=f, VOLUME=v, VOLUMEID=self.volid.get(v, v))
        self.by_key[k] = e
        return k, True

    def _root_subnodes(self):
        pls = self.root.find("PLAYLISTS")
        if pls is None:
            pls = ET.SubElement(self.root, "PLAYLISTS")
        node = pls.find("NODE")
        if node is None:
            node = ET.SubElement(pls, "NODE", TYPE="FOLDER", NAME="$ROOT")
        sub = node.find("SUBNODES")
        if sub is None:
            sub = ET.SubElement(node, "SUBNODES", COUNT="0")
        return sub

    @staticmethod
    def _child(sub, typ, name):
        for n in sub.findall("NODE"):
            if n.get("TYPE") == typ and n.get("NAME") == name:
                return n
        n = ET.SubElement(sub, "NODE", TYPE=typ, NAME=name)
        sub.set("COUNT", str(len(sub.findall("NODE"))))
        return n

    def set_playlist(self, folder, name, keys):
        """Deja la playlist <folder>/<name> con exactamente estas pistas, en este orden. -> cambió?"""
        fnode = self._child(self._root_subnodes(), "FOLDER", folder)
        fsub = fnode.find("SUBNODES")
        if fsub is None:
            fsub = ET.SubElement(fnode, "SUBNODES", COUNT="0")
        pnode = self._child(fsub, "PLAYLIST", name)
        pl = pnode.find("PLAYLIST")
        current = [pk.get("KEY") for pk in pl.iter("PRIMARYKEY")] if pl is not None else None
        if current == keys:
            return False
        if pl is not None:
            pnode.remove(pl)
        pl = ET.SubElement(pnode, "PLAYLIST", ENTRIES=str(len(keys)), TYPE="LIST", UUID=uuid.uuid4().hex)
        for k in keys:
            ET.SubElement(ET.SubElement(pl, "ENTRY"), "PRIMARYKEY", TYPE="TRACK", KEY=k)
        return True

    def rekey(self, old_path, new_path):
        """Un archivo cambió de lugar: su entrada y las playlists que lo usan pasan a la ruta nueva."""
        ok, nk = self.key(old_path), self.key(new_path)
        e = self.by_key.pop(ok, None)
        if e is not None and nk not in self.by_key:
            v, d, f = _split(new_path, self.root_volume)
            loc = e.find("LOCATION")
            loc.set("VOLUME", v), loc.set("DIR", d), loc.set("FILE", f), loc.set("VOLUMEID", self.volid.get(v, v))
            self.by_key[nk] = e
        elif e is not None:
            self.coll.remove(e)
        n = 0
        for pk in self.root.iter("PRIMARYKEY"):
            if pk.get("KEY") == ok:
                pk.set("KEY", nk)
                n += 1
        return n

    def repoint(self, old_path, new_path):
        """Solo las playlists: lo que apuntaba a old pasa a apuntar a new (la entrada vieja se queda)."""
        ok, nk = self.key(old_path), self.key(new_path)
        n = 0
        for pk in self.root.iter("PRIMARYKEY"):
            if pk.get("KEY") == ok:
                pk.set("KEY", nk)
                n += 1
        return n

    def save(self):
        self.coll.set("ENTRIES", str(len(self.coll.findall("ENTRY"))))
        ET.indent(self.tree, space="")
        body = ET.tostring(self.root, encoding="unicode", short_empty_elements=False)  # como lo escribe Traktor
        tmp = self.path.with_name(f".{self.path.name}.brainorder.tmp")
        tmp.write_text('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n' + body, "utf-8")
        os.replace(tmp, self.path)


def backup(path):
    p = Path(path)
    dst = p.with_name(f"collection.brainorder-{datetime.now():%Y%m%d-%H%M%S}.nml.bak")
    shutil.copy2(p, dst)
    for old in sorted(list(p.parent.glob("collection.spotisync-*.nml.bak")) + list(p.parent.glob("collection.brainorder-*.nml.bak")),
                     key=lambda x: x.name.split("-", 1)[-1])[:-5]:  # por la fecha del nombre
        try:
            old.unlink()
        except OSError:
            pass
    return dst.name


def _open(cfg):
    path = nml_path(cfg)
    if not path or not Path(path).exists():
        raise TraktorError("No encontré collection.nml de Traktor. Elige el archivo en Conexiones.")
    if running():
        raise TraktorError("Traktor está abierto. Ciérralo y vuelve a intentarlo.")
    return path


def sync(analysis, cfg, progress=None):
    path = _open(cfg)
    bk = backup(path)
    col = Collection(path)
    folder = cfg.get("rekordbox_folder") or "BrainOrder"
    stats = {"playlists_updated": 0, "tracks_added": 0, "backup": bk}
    analysis = [p for p in analysis if not p.get("pending")]
    for i, pl in enumerate(analysis, 1):
        if progress:
            progress(f"Traktor {i}/{len(analysis)}: {pl['name']}", i / max(1, len(analysis)))
        keys, seen = [], set()
        for r in pl["tracks"]:
            if r["status"] in ("ok", "elsewhere") and r.get("source") and r["source"] not in seen:
                seen.add(r["source"])
                k, new = col.ensure_entry(r["source"], r["name"], ", ".join(r.get("artists") or []))
                stats["tracks_added"] += new
                keys.append(k)
        if col.set_playlist(folder, pl["name"], keys):
            stats["playlists_updated"] += 1
    col.save()
    log(f"Traktor: {stats}")
    return stats


def fix_paths(cfg, moved, repoint=None):
    """moved: {ruta_vieja: ruta_nueva} (el archivo cambió de lugar).
    repoint: {ruta_vieja: ruta_que_se_conserva} (copia repetida apartada: las playlists usan la otra)."""
    path = nml_path(cfg)
    if not path or not Path(path).exists() or not (moved or repoint):
        return None
    _open(cfg)
    bk = backup(path)
    col = Collection(path)
    n = 0
    for old, keep in (repoint or {}).items():
        n += col.repoint(old, keep)
    for old, new in (moved or {}).items():
        n += col.rekey(old, new)
    col.save()
    return {"refs": n, "backup": bk}
