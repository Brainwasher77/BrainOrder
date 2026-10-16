"""Arranque de SpotiSync (solo librería estándar).

Lo ejecuta el lanzador (la app de Mac o el acceso directo de Windows) con el Python del
entorno de SpotiSync. Antes de abrir la ventana:
  1. Si hay una actualización descargada, la instala.
  2. Si falta algún componente (por ejemplo después de reparar el entorno), lo instala.
  3. Abre la app.

Estructura instalada (carpeta de datos de SpotiSync):
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
LOG = SUP / "spotisync.log"
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
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "SpotiSync"'],
                           timeout=5, capture_output=True)
    except Exception:
        pass


def apply_update():
    ready = UPDATE / "ready.json"
    new = UPDATE / "app"
    if not ready.exists() or not (new / "app.py").exists():
        return
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


def ensure_deps():
    miss = missing_modules()
    if not miss:
        return
    log(f"faltan componentes {miss}; instalando…")
    notify("Preparando componentes, puede tardar un par de minutos…")
    req = APP / "requirements.txt"
    args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    args += ["-r", str(req)] if req.exists() else ["pywebview", "pyrekordbox>=0.4", "mutagen", "openpyxl"]
    py = sys.executable
    if IS_WIN and py.lower().endswith("pythonw.exe"):
        args[0] = py[:-len("pythonw.exe")] + "python.exe"
    kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        log(f"pip falló: {r.stderr[-2000:]}")
    import importlib
    importlib.invalidate_caches()


def main():
    apply_update()
    ensure_deps()
    if not (APP / "app.py").exists():
        log("no encuentro el código de la app; vuelve a correr el instalador")
        notify("No encuentro SpotiSync instalado. Vuelve a correr el instalador.")
        sys.exit(1)
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    runpy.run_path(str(APP / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
