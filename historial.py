"""Historial de movimientos de archivos y «Deshacer».

Cada operación que mueve archivos (Organizar, Reorganizar, Unificar) guarda aquí la lista exacta de
(origen, destino). Deshacer devuelve cada archivo a su lugar si:
  - el archivo sigue donde BrainOrder lo dejó, y
  - en su lugar original no apareció otro archivo con el mismo nombre.
Lo que no cumpla eso se salta y se informa: nunca se pisa ni se borra nada.
"""
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from config import SUPPORT_DIR, log

DIR = SUPPORT_DIR / "historial"
KEEP = 50
_LOCK = threading.Lock()
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _path(op_id):
    return DIR / f"{op_id}.json"


def _save(op):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(op["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(op, ensure_ascii=False), "utf-8")
    os.replace(tmp, _path(op["id"]))


def record(kind, label, moves, extra=None):
    """Guarda una operación. moves: [(origen, destino)]. Devuelve el id (o None si no hubo movimientos)."""
    moves = [[str(a), str(b)] for a, b in moves or [] if a and b]
    if not moves:
        return None
    op = {"id": f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}", "time": datetime.now().isoformat(timespec="seconds"),
          "kind": kind, "label": label, "moves": moves, "undone": None, **(extra or {})}
    with _LOCK:
        _save(op)
        ops = sorted(DIR.glob("*.json"))
        for old in ops[:-KEEP]:
            try:
                old.unlink()
            except OSError:
                pass
    return op["id"]


def get(op_id):
    try:
        return json.loads(_path(op_id).read_text("utf-8"))
    except Exception:
        return None


def list_ops(limit=30):
    if not DIR.is_dir():
        return []
    out = []
    for f in sorted(DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            op = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        moves = op.get("moves") or []
        # cuántos se podrían devolver ahora mismo
        ready = sum(1 for a, b in moves if Path(b).exists() and not Path(a).exists())
        out.append({k: op.get(k) for k in ("id", "time", "kind", "label", "undone")} |
                   {"count": len(moves), "ready": ready, "sample": [Path(b).name for _, b in moves[:3]]})
    return out


def plan_undo(op):
    """-> (devolver [(actual, original)], saltados [{file, why}])"""
    todo, skipped = [], []
    for src, dst in reversed(op.get("moves") or []):
        if not Path(dst).exists():
            skipped.append({"file": Path(dst).name, "why": "ya no está donde BrainOrder lo dejó"})
        elif Path(src).exists():
            skipped.append({"file": Path(src).name, "why": "en su lugar original ya hay otro archivo con ese nombre"})
        else:
            todo.append((dst, src))
    return todo, skipped


def apply_undo(op, todo, protect=(), progress=None):
    """Mueve de vuelta. Si algo falla a mitad, devuelve lo ya devuelto (todo o nada)."""
    done = []
    try:
        for n, (cur, orig) in enumerate(todo, 1):
            if progress:
                progress(f"Devolviendo {n}/{len(todo)}: {Path(orig).name}", n / max(1, len(todo)))
            Path(orig).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(cur, orig)
            done.append((cur, orig))
    except Exception as e:
        log(f"Deshacer falló, revirtiendo: {e!r}")
        for cur, orig in reversed(done):
            try:
                shutil.move(orig, cur)
            except Exception as e2:
                log(f"No pude revertir {orig} -> {cur}: {e2}")
        raise
    # carpetas que quedaron vacías por culpa de la operación (nunca las raíces del usuario)
    protect = {os.path.normcase(os.path.normpath(p)) for p in protect if p}
    for cur, _ in done:
        d = Path(cur).parent
        while os.path.normcase(os.path.normpath(str(d))) not in protect and d.parent != d:
            try:
                names = os.listdir(d)
                if not all(x in JUNK for x in names):
                    break
                for x in names:
                    (d / x).unlink()
                d.rmdir()
            except OSError:
                break
            d = d.parent
    op["undone"] = datetime.now().isoformat(timespec="seconds")
    op["undone_count"] = len(done)
    with _LOCK:
        _save(op)
    return {cur: orig for cur, orig in done}
