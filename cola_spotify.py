"""Cola de trabajos para Spotify: lo que no se pudo hacer porque Spotify puso a la app en pausa
(por exceso de consultas) queda aquí y BrainOrder lo hace solo en cuanto Spotify lo permite.

Trabajos (SUPPORT/spotify_cola.json):
    {"id", "kind": "import", "name", "entry": {...}, "local_pid", "origin", "created"}
        crear (o reutilizar) la playlist en Spotify con las canciones de esa carpeta / playlist de DJ;
        mientras tanto vive en BrainOrder como playlist importada sin plataforma.
    {"id", "kind": "add", "name", "path", "pid", "files": [...], "created"}
        agregar a la playlist de Spotify las canciones nuevas de una carpeta vinculada.
    {"id", "kind": "merge_add", "pid", "name", "uris", "paths", "queries", "local_tracks"}
        canciones de una playlist fusionada que faltan en la de Spotify. Mientras esperan, local_tracks
        se muestran en BrainOrder como parte de esa playlist (no desaparecen).
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
        if job["kind"] == "merge_add":
            # varias fusiones hacia la misma playlist mientras Spotify está en pausa: se SUMAN (antes la
            # segunda reemplazaba a la primera y las canciones de la primera nunca llegaban a Spotify)
            prev = next((j for j in jobs if j.get("kind") == "merge_add" and j.get("pid") == job.get("pid")), None)
            if prev is not None:
                for k in ("uris", "paths", "queries", "local_tracks"):
                    seen = [json.dumps(x, sort_keys=True) for x in prev.get(k) or []]
                    for x in job.get(k) or []:
                        if json.dumps(x, sort_keys=True) not in seen:
                            prev.setdefault(k, []).append(x)
                            seen.append(json.dumps(x, sort_keys=True))
                prev["name"] = job.get("name") or prev.get("name")
                _save(jobs)
                return prev
            jobs.append(job)
            _save(jobs)
            return job
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


def pending_tracks(pid):
    """Canciones fusionadas en esa playlist que todavía no llegaron a Spotify (para mostrarlas igual)."""
    out, seen = [], set()
    for j in load():
        if j.get("kind") == "merge_add" and j.get("pid") == pid:
            for t in j.get("local_tracks") or []:
                if t.get("id") and t["id"] not in seen:
                    seen.add(t["id"])
                    out.append(t)
    return out
