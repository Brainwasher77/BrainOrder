"""Fuentes de playlists además de Spotify.

Cada fuente expone:
    KEY, LABEL
    enabled(cfg) -> bool
    list_playlists(cfg, progress) -> [{id, name, snapshot, total, url, source, liked?}]
    tracks(cfg, meta, progress) -> [{id, name, artists, album, duration_ms, url, isrc}]
Los ids de playlist llevan prefijo de la fuente ("dz:", "file:") para no chocar con los de Spotify.
"""
from . import archivos, deezer_src

SOURCES = {m.KEY: m for m in (deezer_src, archivos)}


def source_of(pid: str) -> str:
    for key, m in SOURCES.items():
        if pid.startswith(m.PREFIX):
            return key
    return "spotify"


def settings(cfg, key):
    return (cfg.get("sources") or {}).get(key) or {}
