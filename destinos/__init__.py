"""Programas de DJ a los que se replican las playlists.

Cada destino expone: KEY, LABEL, available(cfg), enabled(cfg), running(),
sync(analysis, cfg, progress) -> stats, fix_paths(cfg, moved, repoint) (rutas tras mover archivos),
edit(cfg, renames, deletes) (renombrar / eliminar playlists dentro de la carpeta de BrainOrder).
"""
from . import engine, m3u, rekordbox, serato, traktor

DESTINATIONS = {m.KEY: m for m in (rekordbox, traktor, serato, engine, m3u)}


def enabled_keys(cfg):
    return [k for k, m in DESTINATIONS.items() if m.enabled(cfg)]


def status(cfg):
    out = {}
    for k, m in DESTINATIONS.items():
        s = (cfg.get("destinations") or {}).get(k) or {}
        info = {"label": m.LABEL, "available": m.available(cfg), "enabled": m.enabled(cfg),
                "running": False}
        try:
            info["running"] = bool(m.running()) if info["enabled"] else False
        except Exception:
            pass
        if k == "traktor":
            info["nml"] = m.nml_path(cfg)
        if k == "m3u":
            info["folder"] = m.folder(cfg)
        if k == "serato":
            info["dir"] = str(m.home_serato(cfg))
        if k == "engine":
            info["dir"] = str(m.library_dir(cfg))
        info["wanted"] = bool(s.get("enabled", k == "rekordbox"))
        out[k] = info
    return out
