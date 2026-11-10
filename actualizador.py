"""Actualizaciones automáticas desde GitHub.

Al abrir la app se revisa (en segundo plano) si en GitHub hay un version.json con un
número de build mayor. Si lo hay, se descarga el código nuevo a <datos>/update/ y se
instala solo la próxima vez que se abra BrainOrder (o al tocar "Reiniciar").
"""
import io
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from config import SUPPORT_DIR, log

REPOS = ["Brainwasher77/BrainOrder"]
BRANCH = "main"
_repo = [None]  # el que respondió


def _version_url(repo):
    return f"https://raw.githubusercontent.com/{repo}/{BRANCH}/version.json"


def _zip_url(repo):
    return f"https://codeload.github.com/{repo}/zip/refs/heads/{BRANCH}"


def _remote_version(timeout=8):
    last = None
    for repo in REPOS:
        try:
            data = json.loads(_get(_version_url(repo), timeout=timeout))
            _repo[0] = repo
            return data
        except Exception as e:
            last = e
    raise last
HERE = Path(__file__).resolve().parent
UPDATE = SUPPORT_DIR / "update"


HOSTS = {"raw.githubusercontent.com", "codeload.github.com"}
MAX_ZIP = 80 * 1024 * 1024      # el paquete pesa unos pocos MB: algo mucho más grande no es BrainOrder
MAX_UNPACKED = 250 * 1024 * 1024


class _SoloGitHub(urllib.request.HTTPRedirectHandler):
    """Una redirección solo se sigue si lleva a GitHub por HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in HOSTS:
        raise RuntimeError(f"dirección no permitida para actualizar: {url[:120]}")


def _get(url, timeout=15, limit=2 * 1024 * 1024):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "BrainOrder-updater", "Cache-Control": "no-cache"})
    with urllib.request.build_opener(_SoloGitHub).open(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("la descarga es más grande de lo esperado")
    return data


def _unpack(data, dest):
    """Descomprime el paquete revisando cada entrada: nada fuera de la carpeta, sin enlaces, tamaño razonable."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise RuntimeError("el paquete descomprimido es demasiado grande")
        for i in infos:
            name = i.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or (len(name) > 1 and name[1] == ":"):
                raise RuntimeError(f"ruta rara dentro del paquete: {i.filename[:80]}")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError(f"el paquete trae un enlace: {i.filename[:80]}")
            if dest not in (dest / name).resolve().parents and (dest / name).resolve() != dest:
                raise RuntimeError(f"ruta fuera del paquete: {i.filename[:80]}")
        z.extractall(dest)


def _verify(src, remote):
    """El paquete tiene que ser BrainOrder, de la versión anunciada (o más nueva) y con código que compile:
    una descarga a medias o mezclada (GitHub publicando justo en ese momento) no se instala."""
    src = Path(src)
    for need in ("app.py", "arranque.py", "ui.html", "config.py", "version.json"):
        if not (src / need).is_file():
            raise RuntimeError(f"el paquete descargado no parece BrainOrder (falta {need})")
    try:
        got = json.loads((src / "version.json").read_text("utf-8"))
        build = int(got.get("build", 0))
    except Exception:
        raise RuntimeError("el paquete trae un version.json ilegible")
    if build < int(remote.get("build", 0)):
        raise RuntimeError(f"el paquete es de una versión anterior (build {build}): se reintenta después")
    for f in sorted(src.rglob("*.py")):
        try:
            compile(f.read_bytes(), str(f), "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as e:
            raise RuntimeError(f"el paquete trae un archivo dañado ({f.name}: {e})")
    return got


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
        remote = _remote_version()
    except Exception as e:
        log(f"actualizador: no pude revisar versiones ({e})")
        return {"status": "error", "current": cur}
    if int(remote.get("build", 0)) <= int(cur.get("build", 0)):
        return {"status": "up_to_date", "current": cur}
    try:  # esa versión ya falló al arrancar en esta compu: esperar a la siguiente
        skip = json.loads((SUPPORT_DIR / "update_skip.json").read_text("utf-8")).get("build")
        if skip is not None and int(skip) == int(remote.get("build", 0)):
            return {"status": "up_to_date", "current": cur}
    except Exception:
        pass
    p = pending()
    if p and int(p.get("build", 0)) >= int(remote.get("build", 0)):
        return {"status": "ready", "current": cur, "new": p}
    try:
        if progress:
            progress(f"Descargando BrainOrder {remote.get('version')}…")
        data = _get(_zip_url(_repo[0] or REPOS[0]), timeout=60, limit=MAX_ZIP)
        with tempfile.TemporaryDirectory() as tmp:
            _unpack(data, tmp)
            roots = [d for d in Path(tmp).iterdir() if d.is_dir()]
            src = roots[0] if len(roots) == 1 else Path(tmp)
            got = _verify(src, remote)
            if UPDATE.exists():
                shutil.rmtree(UPDATE, ignore_errors=True)
            UPDATE.mkdir(parents=True)
            shutil.copytree(src, UPDATE / "app")
        # lo que se instala es lo que trae el paquete (no lo que decía el aviso)
        info = {"version": got.get("version"), "build": got.get("build"), "notes": got.get("notes", "")}
        from config import write_atomic
        write_atomic(UPDATE / "ready.json", json.dumps(info, ensure_ascii=False))  # se escribe al final y entero
        log(f"actualizador: versión {info['version']} descargada, se instala al reiniciar")
        return {"status": "ready", "current": cur, "new": info}
    except Exception as e:
        log(f"actualizador: no pude descargar la versión nueva ({e})")
        shutil.rmtree(UPDATE, ignore_errors=True)
        return {"status": "error", "current": cur}
