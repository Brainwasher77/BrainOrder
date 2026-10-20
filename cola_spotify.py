"""Cola de trabajos para Spotify: lo que no se pudo hacer porque Spotify puso a la app en pausa
(por exceso de consultas) queda aquí y BrainOrder lo hace solo en cuanto Spotify lo permite.

Trabajos (SUPPORT/spotify_cola.json):
    {"id", "kind": "import", "name", "entry": {...}, "local_pid", "origin", "created"}
        crear (o reutilizar) la playlist en Spotify con las canciones de esa carpeta / playlist de DJ;
        mientras tanto vive en BrainOrder como playlist importada sin plataforma.
    {"id", "kind": "add", "name", "path", "pid", "files": [...], "created"}
        agregar a la playlist de Spotify las canciones nuevas de una carpeta vinculada.
"""
import json
import threading
import uuid
from datetime import datetime

from config import SUPPORT_DIR, write_atomic

FILE = SUPPORT_DIR / "spotify_cola.json"
_LOCK = threading.Lock()


def load():
    try:
        data = json.loads(FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(jobs):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(FILE, json.dumps(jobs, ensure_ascii=False))


def add(job):
    with _LOCK:
        jobs = load()
        job = {"id": uuid.uuid4().hex[:10], "created": datetime.now().isoformat(timespec="seconds"), "tries": 0, **job}
        # el mismo trabajo dos veces no: se reemplaza por el más nuevo
        same = (lambda j: j.get("kind") == job["kind"] and j.get("name") == job.get("name")
                and (j.get("entry") or {}) == (job.get("entry") or {}) and j.get("path") == job.get("path"))
        jobs = [j for j in jobs if not same(j)] + [job]
        _save(jobs)
        return job


def remove(job_id):
    with _LOCK:
        _save([j for j in load() if j.get("id") != job_id])


def update(job_id, **changes):
    with _LOCK:
        jobs = load()
        for j in jobs:
            if j.get("id") == job_id:
                j.update(changes)
        _save(jobs)


def summary():
    return [{"id": j["id"], "kind": j["kind"], "name": j.get("name"), "created": j.get("created"),
             "error": j.get("error"), "count": len(j.get("files") or []) + len(j.get("uris") or []) + len(j.get("paths") or [])
             + len(j.get("queries") or [])} for j in load()]
