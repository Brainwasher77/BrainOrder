"""Escribe en cada carpeta de playlist un .txt con las canciones que no están ahí y su origen."""
from datetime import datetime
from pathlib import Path

from config import log

TXT_NAME = "_FALTAN EN ESTA CARPETA.txt"


def _short(p: str) -> str:
    home = str(Path.home())
    return p.replace(home, "~", 1) if p else p


def _label(r):
    return f"{', '.join(r['artists'])} - {r['name']}" if r["artists"] else r["name"]


def write_reports(analysis, cfg):
    """Crea/actualiza el .txt de cada playlist. Si no le falta nada, borra el .txt viejo."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    written = 0
    for pl in analysis:
        if pl.get("pending"):
            continue  # playlist todavía sin analizar: no tocar su .txt
        folder = Path(pl["folder"])
        txt = folder / TXT_NAME
        here = [r for r in pl["tracks"] if r["status"] == "ok" and r["source"]
                and str(Path(r["source"]).parent) == pl["folder"]]
        here_ids = {id(r) for r in here}
        others = [r for r in pl["tracks"] if id(r) not in here_ids]  # antes «r not in here»: lentísimo en listas grandes
        try:
            if not others:
                if txt.exists():
                    txt.unlink()
                continue
            elsewhere = [r for r in others if r["status"] in ("ok", "elsewhere")]
            inbox = [r for r in others if r["status"] == "inbox"]
            missing = [r for r in others if r["status"] == "missing"]
            L = [f"BrainOrder — {pl['name']}",
                 f"Actualizado: {now}",
                 f"Esta carpeta tiene {len(here)} de {len(pl['tracks'])} canciones de la playlist.",
                 "Las demás no están aquí para no duplicar archivos; abajo está dónde encontrarlas.", ""]
            if elsewhere:
                L.append(f"EN OTRA CARPETA ({len(elsewhere)})")
                for r in elsewhere:
                    L.append(f"  {r['pos'] + 1:>4}. {_label(r)}")
                    L.append(f"        → {_short(str(Path(r['source']).parent))}/")
                    L.append(f"          {Path(r['source']).name}")
                L.append("")
            if inbox:
                L.append(f"EN DESCARGAS, POR ORGANIZAR ({len(inbox)})")
                for r in inbox:
                    L.append(f"  {r['pos'] + 1:>4}. {_label(r)}")
                    L.append(f"        → {_short(r['source'])}  (irá a: {r.get('home_name', '')})")
                L.append("")
            if missing:
                L.append(f"POR DESCARGAR ({len(missing)})")
                for r in missing:
                    extra = f"  (irá a: {r.get('home_name')})" if r.get("home_name") and r.get("home_name") != pl["name"] else ""
                    L.append(f"  {r['pos'] + 1:>4}. {_label(r)}{extra}")
                    if r.get("url"):
                        L.append(f"        Spotify: {r['url']}")
                    dz = r.get("deezer") or {}
                    if dz.get("url"):
                        L.append(f"        Deezer:  {dz['url']}" + ("" if dz.get("found") else "  (búsqueda)"))
                L.append("")
            body = "\n".join(L)
            try:  # si solo cambiaría la fecha, no se reescribe (cientos de carpetas en cada análisis)
                old = txt.read_text("utf-8").split("\n")
                if old[:1] + old[2:] == L[:1] + L[2:]:
                    continue
            except OSError:
                pass
            folder.mkdir(parents=True, exist_ok=True)
            txt.write_text(body, encoding="utf-8")
            written += 1
        except Exception as e:
            log(f"No pude escribir el reporte de {pl['name']}: {e}")
    return written
