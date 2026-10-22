"""¿Qué hay de NUEVO en una playlist que creaste en Rekordbox (u otro programa de DJ)?

Antes de preguntarte si la importas, BrainOrder revisa canción por canción si ya la tiene:
    ya_en_brainorder  el mismo archivo ya es de una de tus playlists de BrainOrder
    copia             es una copia exacta de un archivo que ya está en BrainOrder (mismo contenido)
    misma_cancion     es la misma canción (artista + título + versión + duración) que ya tienes
Lo demás es música nueva. También mira si ya hay una playlist de BrainOrder con ese nombre
(sin importar tildes, emojis o mayúsculas): en ese caso no se crea otra, se le suma lo nuevo.

Nunca se borra nada: lo repetido simplemente no se importa (el archivo se queda donde está).
"""
import os
from collections import defaultdict
from pathlib import Path

import biblioteca as b
from duplicados import _quick_hash

USED_STATUS = ("ok", "elsewhere")


def _key(p):
    return os.path.normcase(os.path.normpath(str(p)))


def _akey(f):
    return f.artist_n.split(" and ")[0].split(",")[0].strip()


def _song_key(f):
    if not f.core or _akey(f) in b.UNKNOWN_ARTISTS:
        return None
    return (_akey(f), f.core, f.extras)


def _local(path):
    p = Path(path)
    artist, title = b.parse_file(p)
    return b.LocalFile(p, artist, title)


class Biblioteca:
    """Lo que ya está en BrainOrder (los archivos de tus playlists), listo para comparar rápido."""

    def __init__(self, analysis):
        self.paths = {}            # ruta normalizada -> nombre de la playlist
        self.by_song = defaultdict(list)
        self.by_size = defaultdict(list)
        self._parsed = False
        for pl in analysis or []:
            for r in pl.get("tracks") or []:
                src = r.get("source")
                if src and r.get("status") in USED_STATUS:
                    self.paths.setdefault(_key(src), pl.get("name") or "")
        self.names = {}            # nombre normalizado -> playlist
        for pl in analysis or []:
            k = b.folder_key(pl.get("name") or "")
            if k and k not in self.names:
                self.names[k] = pl

    def _parse(self):
        if self._parsed:
            return
        self._parsed = True
        for k in self.paths:
            if not os.path.exists(k):
                continue
            try:
                self.by_size[os.path.getsize(k)].append(k)
            except OSError:
                pass
            f = _local(k)
            sk = _song_key(f)
            if sk:
                self.by_song[sk].append(k)

    def playlist_named(self, name):
        """Playlist de BrainOrder con el mismo nombre (o equivalente: tildes, emojis, mayúsculas)."""
        k = b.folder_key(name or "")
        if not k:
            return None
        if k in self.names:
            return self.names[k]
        for kk, pl in self.names.items():
            if b.similar_folders(kk, k):
                return pl
        return None

    def check(self, path):
        """-> (motivo, ruta que ya tienes) o (None, None) si es nueva."""
        k = _key(path)
        if k in self.paths:
            return "ya_en_brainorder", path
        if not os.path.exists(path):
            return "no_existe", None
        self._parse()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        if size is not None and self.by_size.get(size):
            h = _quick_hash(path)
            for other in self.by_size[size]:
                if other != k and h and _quick_hash(other) == h:
                    return "copia", other
        sk = _song_key(_local(path))
        if sk and self.by_song.get(sk):
            d = b.duration(path)
            for other in self.by_song[sk]:
                if other != k and b.same_length(d, b.duration(other)):
                    return "misma_cancion", other
        return None, None


def novelty(cfg, analysis, name, paths, lib=None):
    """Revisa una playlist. -> {new: [rutas], have: [{file, why, existing}], missing: n, existing: playlist o None}"""
    b.configure(cfg)
    lib = lib or Biblioteca(analysis)
    new, have, missing, seen = [], [], 0, set()
    for p in paths or []:
        k = _key(p)
        if k in seen:
            continue  # la misma canción dos veces en la playlist de Rekordbox
        seen.add(k)
        why, other = lib.check(p)
        if why is None:
            new.append(p)
        elif why == "no_existe":
            missing += 1
        else:
            have.append({"file": p, "why": why, "existing": other})
    # dentro de la misma playlist nueva: dos archivos que son la misma canción cuentan una vez
    uniq, songs = [], {}
    for p in new:
        f = _local(p)
        sk = _song_key(f)
        twin = None
        if sk and sk in songs:
            d = b.duration(p)
            twin = next((o for o in songs[sk] if b.same_length(d, b.duration(o))), None)
        if twin:
            have.append({"file": p, "why": "repetida_en_la_playlist", "existing": twin})
            continue
        if sk:
            songs.setdefault(sk, []).append(p)
        uniq.append(p)
    ex = lib.playlist_named(name)
    return {"new": uniq, "have": have, "missing": missing,
            "existing": ({"id": ex["id"], "name": ex["name"], "source": ex.get("source")} if ex else None)}
