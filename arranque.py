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
  venv/         <- entorno de Python (instalación con el script; la del instalador trae su propio Python)
  componentes/  <- (instalador .dmg/.exe) componentes nuevos que pidió una actualización

Con el instalador (.dmg / .exe) el código viene dentro del programa y se ejecuta así:
  python arranque.py --seed     (desde el código que trae el programa)
Si el programa trae una versión más nueva que la instalada (o no hay ninguna), la copia a <datos>/app
y sigue con el arranque normal desde <datos>/arranque.py (así las actualizaciones automáticas funcionan igual).
"""
import json
import os
import runpy
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
SEED = "--seed" in sys.argv[1:]  # lo usa el programa instalado (.dmg / .exe)


def _support_dir():
    home = Path.home()
    if IS_WIN:
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    new, old = base / "BrainOrder", base / "SpotiSync"  # datos de las primeras versiones: se trasladan una vez
    if not new.exists() and old.exists():
        try:
            os.rename(old, new)
        except OSError:
            return old
    return new


SUP = _support_dir() if SEED else Path(__file__).resolve().parent
if SEED:
    os.environ["BRAINORDER_PACKAGED"] = "1"
PACKAGED = os.environ.get("BRAINORDER_PACKAGED") == "1"
EXTRA = SUP / "componentes"
APP = SUP / "app"
UPDATE = SUP / "update"
LOG = SUP / "brainorder.log"
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


def _build(folder):
    try:
        return int(json.loads((Path(folder) / "version.json").read_text("utf-8")).get("build", 0))
    except Exception:
        return -1


def seed_from_bundle(bundle):
    """El programa instalado (.dmg / .exe) trae el código: si es más nuevo que el instalado (o no hay), se copia."""
    bundle = Path(bundle)
    have, new_b = _build(APP) if (APP / "app.py").exists() else -1, _build(bundle)
    if new_b <= have:
        return False
    SUP.mkdir(parents=True, exist_ok=True)
    tmp = SUP / "app.new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(bundle, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    prev = SUP / "app.prev"
    shutil.rmtree(prev, ignore_errors=True)
    if APP.exists():
        APP.rename(prev)
    tmp.rename(APP)
    shutil.copy2(APP / "arranque.py", SUP / "arranque.py")
    # una actualización descargada que no es más nueva que esta ya no sirve
    try:
        if int(json.loads((UPDATE / "ready.json").read_text("utf-8")).get("build", 0)) <= new_b:
            shutil.rmtree(UPDATE, ignore_errors=True)
    except Exception:
        pass
    # el programa trae sus componentes: los que se agregaron después ya no hacen falta
    shutil.rmtree(EXTRA, ignore_errors=True)
    _write(SUP / ".componentes", _req_stamp())
    log(f"programa instalado: código versión build {new_b} (antes {have})")
    return True


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
    if PACKAGED:  # el Python del programa no se toca: lo nuevo va a <datos>/componentes
        EXTRA.mkdir(parents=True, exist_ok=True)
        args += ["--upgrade", "--target", str(EXTRA)]
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
    if PACKAGED and EXTRA.is_dir() and str(EXTRA) not in sys.path:
        sys.path.insert(0, str(EXTRA))
    if SEED:
        try:
            seed_from_bundle(Path(__file__).resolve().parent)
        except Exception as e:
            log(f"no pude copiar el código del programa: {e!r}")
        mine, inst = Path(__file__).resolve(), SUP / "arranque.py"
        if inst.exists() and inst.resolve() != mine:
            # el arranque instalado puede ser más nuevo (llegó con una actualización): manda ese
            sys.argv = [str(inst)]
            for m in [k for k in sys.modules if k not in _BASE_MODULES]:
                sys.modules.pop(m, None)
            runpy.run_path(str(inst), run_name="__main__")
            return
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
