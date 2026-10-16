"""Organiza descargas sin duplicar archivos.

- Cada descarga se MUEVE (no se copia) a la carpeta hogar de su canción.
- Las descargas de canciones que ya tienes van a <descargas>/_duplicados para que las borres tú.
- Los archivos que ya están en otras carpetas de tu biblioteca no se tocan.
- Nunca se borra nada.
"""
import shutil
from pathlib import Path

from config import log


def _unique(dst: Path) -> Path:
    if not dst.exists():
        return dst
    i = 2
    while True:
        cand = dst.with_name(f"{dst.stem} ({i}){dst.suffix}")
        if not cand.exists():
            return cand
        i += 1


def plan(analysis):
    """(movimientos {src: dest_dir}, duplicados {src})"""
    moves, dups = {}, set()
    for pl in analysis:
        for r in pl["tracks"]:
            if r["status"] == "inbox" and r["source"]:
                moves.setdefault(r["source"], r["dest_dir"])
            dups.update(r.get("inbox_dups") or [])
    dups -= set(moves)
    return moves, dups


def organize(analysis, cfg, progress=None):
    moves, dups = plan(analysis)
    inbox = Path(cfg["inbox"])
    dup_dir = inbox / "_duplicados"
    moved, to_dups, errors = 0, 0, []
    total = len(moves) + len(dups)
    n = 0

    def to_duplicates(src_p: Path):
        rel = src_p.relative_to(inbox) if inbox in src_p.parents else Path(src_p.name)
        target = _unique(dup_dir / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(target))

    for src, dest_dir in moves.items():
        n += 1
        src_p = Path(src)
        if progress:
            progress(f"Organizando {n}/{total}: {src_p.name}")
        try:
            if not src_p.exists():
                continue
            dd = Path(dest_dir)
            dd.mkdir(parents=True, exist_ok=True)
            dst = dd / src_p.name
            if dst.exists():
                # ya hay un archivo con ese nombre en la carpeta: no se duplica
                to_duplicates(src_p)
                to_dups += 1
            else:
                shutil.move(str(src_p), str(dst))
                moved += 1
        except Exception as e:
            errors.append(f"{src_p.name}: {e}")
            log(f"Error moviendo {src} -> {dest_dir}: {e}")

    for src in dups:
        n += 1
        src_p = Path(src)
        if progress:
            progress(f"Organizando {n}/{total}: {src_p.name} (ya la tenías)")
        try:
            if src_p.exists():
                to_duplicates(src_p)
                to_dups += 1
        except Exception as e:
            errors.append(f"{src_p.name}: {e}")
            log(f"Error moviendo duplicado {src}: {e}")

    log(f"Organizar: {moved} movidos, {to_dups} a _duplicados, {len(errors)} errores")
    return {"moved": moved, "duplicates": to_dups, "errors": errors}
