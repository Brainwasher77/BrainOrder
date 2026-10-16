"""Actualizaciones automáticas desde GitHub.

Al abrir la app se revisa (en segundo plano) si en GitHub hay un version.json con un
número de build mayor. Si lo hay, se descarga el código nuevo a <datos>/update/ y se
instala solo la próxima vez que se abra SpotiSync (o al tocar "Reiniciar").
"""
import io
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from config import SUPPORT_DIR, log

REPO = "Brainwasher77/SpotiSync"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.json"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
HERE = Path(__file__).resolve().parent
UPDATE = SUPPORT_DIR / "update"


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "SpotiSync-updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def local_version():
    try:
        return json.loads((HERE / "version.json").read_text("utf-8"))
    except Exception:
        return {"version": "?", "build": 0}


def installed_layout():
    """True si la app corre desde la instalación (<datos>/app) y no desde una carpeta de desarrollo."""
    return HERE == (SUPPORT_DIR / "app").resolve()


def pending():
    try:
        return json.loads((UPDATE / "ready.json").read_text("utf-8"))
    except Exception:
        return None


def check_and_download(progress=None):
    """Devuelve {'status': 'up_to_date'|'ready'|'dev'|'error', ...}."""
    cur = local_version()
    if not installed_layout():
        return {"status": "dev", "current": cur}
    try:
        remote = json.loads(_get(VERSION_URL, timeout=8))
    except Exception as e:
        log(f"actualizador: no pude revisar versiones ({e})")
        return {"status": "error", "current": cur}
    if int(remote.get("build", 0)) <= int(cur.get("build", 0)):
        return {"status": "up_to_date", "current": cur}
    p = pending()
    if p and int(p.get("build", 0)) >= int(remote.get("build", 0)):
        return {"status": "ready", "current": cur, "new": p}
    try:
        if progress:
            progress(f"Descargando SpotiSync {remote.get('version')}…")
        data = _get(ZIP_URL, timeout=60)
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
            roots = [d for d in Path(tmp).iterdir() if d.is_dir()]
            src = roots[0] if len(roots) == 1 else Path(tmp)
            if not (src / "app.py").exists() or not (src / "arranque.py").exists():
                raise RuntimeError("el paquete descargado no parece SpotiSync")
            if UPDATE.exists():
                shutil.rmtree(UPDATE, ignore_errors=True)
            UPDATE.mkdir(parents=True)
            shutil.copytree(src, UPDATE / "app")
        info = {"version": remote.get("version"), "build": remote.get("build"), "notes": remote.get("notes", "")}
        (UPDATE / "ready.json").write_text(json.dumps(info, ensure_ascii=False), "utf-8")
        log(f"actualizador: versión {info['version']} descargada, se instala al reiniciar")
        return {"status": "ready", "current": cur, "new": info}
    except Exception as e:
        log(f"actualizador: no pude descargar la versión nueva ({e})")
        shutil.rmtree(UPDATE, ignore_errors=True)
        return {"status": "error", "current": cur}
