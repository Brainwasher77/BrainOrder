"""Rekordbox como destino (escribe en master.db; ver rekordbox_sync)."""
import rekordbox_sync

KEY = "rekordbox"
LABEL = "Rekordbox"


def available(cfg):
    return (rekordbox_sync.RB_DIR / "master.db").exists()


def enabled(cfg):
    s = (cfg.get("destinations") or {}).get(KEY)
    return available(cfg) and (s is None or bool(s.get("enabled", True)))


def running():
    return rekordbox_sync.rekordbox_running()


def sync(analysis, cfg, progress=None):
    return rekordbox_sync.sync(analysis, cfg, progress)


def fix_paths(cfg, moved, repoint=None):
    return None  # Reorganizar y Unificar ya corrigen Rekordbox por su cuenta
