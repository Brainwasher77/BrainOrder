"""Exporta cada playlist como .m3u8: sirve para cualquier programa que importe M3U
(Serato, VirtualDJ, Engine DJ, djay, Mixxx…). Rutas absolutas y en el orden de la playlist."""
import os
from pathlib import Path

from config import log, safe_name

KEY = "m3u"
LABEL = "Playlists M3U"


def folder(cfg):
    return ((cfg.get("destinations") or {}).get(KEY) or {}).get("folder") or ""


def available(cfg):
    return True


def enabled(cfg):
    return bool(((cfg.get("destinations") or {}).get(KEY) or {}).get("enabled")) and bool(folder(cfg))


def running():
    return False


def sync(analysis, cfg, progress=None):
    out = Path(folder(cfg))
    sub = out / safe_name(cfg.get("rekordbox_folder") or "BrainOrder")
    sub.mkdir(parents=True, exist_ok=True)
    stats = {"playlists_updated": 0, "tracks_added": 0, "folder": str(sub)}
    analysis = [p for p in analysis if not p.get("pending")]
    for i, pl in enumerate(analysis, 1):
        if progress:
            progress(f"M3U {i}/{len(analysis)}: {pl['name']}", i / max(1, len(analysis)))
        lines, seen = ["#EXTM3U", f"#PLAYLIST:{pl['name']}"], set()
        for r in pl["tracks"]:
            if r["status"] in ("ok", "elsewhere") and r.get("source") and r["source"] not in seen:
                seen.add(r["source"])
                artist = ", ".join(r.get("artists") or [])
                lines.append(f"#EXTINF:-1,{artist} - {r['name']}" if artist else f"#EXTINF:-1,{r['name']}")
                lines.append(r["source"])
        target = sub / f"{safe_name(pl['name'])}.m3u8"
        text = "\n".join(lines) + "\n"
        if target.exists() and target.read_text("utf-8", "replace") == text:
            continue
        tmp = target.with_name("." + target.name + ".tmp")
        tmp.write_text(text, "utf-8")
        os.replace(tmp, target)
        stats["playlists_updated"] += 1
    log(f"M3U: {stats}")
    return stats


def fix_paths(cfg, moved, repoint=None):
    return None  # se regeneran en el próximo Organizar


def edit(cfg, renames=None, deletes=None):
    """Las .m3u8 que genera BrainOrder: se renombran o se quitan (no son música)."""
    if not folder(cfg):
        return None
    sub = Path(folder(cfg)) / safe_name(cfg.get("rekordbox_folder") or "BrainOrder")
    f = lambda name: sub / f"{safe_name(name)}.m3u8"
    out = {"renamed": 0, "deleted": 0}
    for old, new in (renames or {}).items():
        if f(old).exists():
            if f(new).exists():
                f(old).unlink()
                out["deleted"] += 1
            else:
                text = f(old).read_text("utf-8", "replace").replace(f"#PLAYLIST:{old}", f"#PLAYLIST:{new}", 1)
                f(new).write_text(text, "utf-8")
                f(old).unlink()
                out["renamed"] += 1
    for name in deletes or []:
        if f(name).exists():
            f(name).unlink()
            out["deleted"] += 1
    return out
