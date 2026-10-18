"""Arranque de BrainOrder (solo librería estándar).

Lo ejecuta el lanzador (la app de Mac o el acceso directo de Windows) con el Python del
entorno de BrainOrder. Antes de abrir la ventana:
  1. Si hay una actualización descargada, la instala.
  2. Si falta algún componente (por ejemplo después de reparar el entorno), lo instala.
  3. Abre la app.

Estructura instalada (carpeta de datos de BrainOrder):
  arranque.py   <- este archivo
  app/          <- código de la app
  update/       <- versión nueva descargada, esperando el próximo arranque
  venv/         <- entorno de Python
"""
import json
import os
import runpy
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SUP = Path(__file__).resolve().parent
APP = SUP / "app"
UPDATE = SUP / "update"
LOG = SUP / "brainorder.log"
IS_WIN = sys.platform.startswith("win")
NEEDED = ("webview", "pyrekordbox", "mutagen", "openpyxl")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] arranque: {msg}\n")
    except Exception:
        pass


def notify(msg):
    """Aviso del sistema (sin depender de la ventana de la app)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "BrainOrder"'],
                           timeout=5, capture_output=True)
    except Exception:
        pass


def apply_update():
    """-> la info de la versión instalada ahora (o None si no había actualización)."""
    ready = UPDATE / "ready.json"
    new = UPDATE / "app"
    if not ready.exists() or not (new / "app.py").exists():
        return None
    try:
        info = json.loads(ready.read_text("utf-8"))
        prev = SUP / "app.prev"
        if prev.exists():
            shutil.rmtree(prev, ignore_errors=True)
        if APP.exists():
            APP.rename(prev)
        shutil.move(str(new), str(APP))
        # el arranque también se actualiza (se usa desde el próximo inicio)
        if (APP / "arranque.py").exists():
            shutil.copy2(APP / "arranque.py", SUP / "arranque.py")
        shutil.rmtree(UPDATE, ignore_errors=True)
        log(f"actualizado a la versión {info.get('version')}")
        return info
    except Exception as e:
        log(f"no pude aplicar la actualización: {e!r}")
        # si algo falló, volver a la versión anterior
        if not (APP / "app.py").exists() and (SUP / "app.prev" / "app.py").exists():
            shutil.rmtree(APP, ignore_errors=True)
            (SUP / "app.prev").rename(APP)


def missing_modules():
    out = []
    for m in NEEDED:
        try:
            __import__(m)
        except Exception:
            out.append(m)
    return out


def _req_stamp():
    import hashlib
    req = APP / "requirements.txt"
    try:
        return hashlib.sha1(req.read_bytes()).hexdigest()
    except OSError:
        return ""


def ensure_deps():
    """Instala componentes que falten, o los de una actualización que pida componentes nuevos."""
    stamp_file = SUP / ".componentes"
    want = _req_stamp()
    try:
        have = stamp_file.read_text("utf-8").strip()
    except OSError:
        have = None
    miss = missing_modules()
    if not miss and have is None:
        _write(stamp_file, want)  # instalación anterior a este control: ya está todo
        return
    if not miss and have == want:
        return
    why = f"faltan componentes {miss}" if miss else "la versión nueva usa componentes distintos"
    log(f"{why}; instalando…")
    notify("Preparando componentes, puede tardar un par de minutos…")
    req = APP / "requirements.txt"
    args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    args += ["-r", str(req)] if req.exists() else ["pywebview", "pyrekordbox>=0.4", "mutagen", "openpyxl"]
    py = sys.executable
    if IS_WIN and py.lower().endswith("pythonw.exe"):
        args[0] = py[:-len("pythonw.exe")] + "python.exe"
    kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=900, **kw)
        if r.returncode != 0:
            log(f"pip falló: {r.stderr[-2000:]}")
        else:
            _write(stamp_file, want)
    except Exception as e:
        log(f"pip no terminó: {e!r}")
    import importlib
    importlib.invalidate_caches()


def _write(p, text):
    try:
        p.write_text(text, "utf-8")
    except OSError:
        pass


def rollback(info):
    """La versión recién instalada no arrancó: se vuelve a la anterior y no se reintenta esa versión."""
    prev = SUP / "app.prev"
    if not (prev / "app.py").exists():
        return False
    bad = SUP / "app.fallida"
    shutil.rmtree(bad, ignore_errors=True)
    try:
        APP.rename(bad)
        prev.rename(APP)
        if (APP / "arranque.py").exists():
            shutil.copy2(APP / "arranque.py", SUP / "arranque.py")
        (SUP / "update_skip.json").write_text(json.dumps({"build": (info or {}).get("build")}), "utf-8")
        log(f"la versión {(info or {}).get('version')} no arrancó: volví a la anterior")
        notify("La actualización no arrancó bien: volví a la versión anterior.")
        return True
    except Exception as e:
        log(f"no pude volver a la versión anterior: {e!r}")
        return False


def run_app():
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    runpy.run_path(str(APP / "app.py"), run_name="__main__")


def main():
    info = apply_update()
    ensure_deps()
    if not (APP / "app.py").exists():
        log("no encuentro el código de la app; vuelve a correr el instalador")
        notify("No encuentro BrainOrder instalado. Vuelve a correr el instalador.")
        sys.exit(1)
    try:
        run_app()
    except Exception:
        import traceback
        log("la app no arrancó:\n" + traceback.format_exc())
        if info and rollback(info):
            for m in [k for k in sys.modules if k not in _BASE_MODULES]:
                sys.modules.pop(m, None)
            sys.path.remove(str(APP)) if str(APP) in sys.path else None
            run_app()
        else:
            raise


_BASE_MODULES = set(sys.modules)

if __name__ == "__main__":
    main()
