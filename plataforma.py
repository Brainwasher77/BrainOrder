"""Todo lo que cambia entre macOS y Windows, en un solo lugar."""
import os
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
HOME = Path.home()


def support_dir() -> Path:
    """Instalación, ajustes, token, cachés y log de BrainOrder.
    Instalaciones hechas cuando la app se llamaba SpotiSync siguen usando su carpeta (no se mueve nada
    mientras la app corre); el instalador nuevo la renombra a BrainOrder."""
    new, old = _support_base() / "BrainOrder", _support_base() / "SpotiSync"
    return new if new.exists() or not old.exists() else old


def _support_base() -> Path:
    if IS_WIN:
        return Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
    if IS_MAC:
        return HOME / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))


def rekordbox_dir() -> Path:
    """Carpeta donde Rekordbox 6/7 guarda master.db."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming")) / "Pioneer" / "rekordbox"
    return HOME / "Library" / "Pioneer" / "rekordbox"


# ---------------- rutas tal como las guarda Rekordbox ----------------
def rb_path(p) -> str:
    """Rekordbox guarda rutas con '/', también en Windows (C:/Users/...)."""
    return str(p).replace("\\", "/")


def native(p) -> str:
    """Ruta de Rekordbox -> ruta del sistema (con '\\' en Windows)."""
    return os.path.normpath(p) if IS_WIN else str(p)


# ---------------- abrir cosas ----------------
def _popen(args):
    try:
        subprocess.Popen(args)
    except Exception:
        pass


def open_path(p):
    """Abre un archivo o carpeta con la app predeterminada."""
    p = str(p)
    if IS_WIN:
        try:
            os.startfile(p)  # noqa: S606 (solo existe en Windows)
        except Exception:
            pass
    elif IS_MAC:
        _popen(["open", p])
    else:
        _popen(["xdg-open", p])


def reveal(p):
    """Muestra el archivo seleccionado en Finder / Explorador."""
    p = Path(p)
    if not p.exists():
        if p.parent.exists():
            open_path(p.parent)
        return
    if IS_WIN:
        if p.is_file():
            _popen(["explorer", f"/select,{p}"])
        else:
            _popen(["explorer", str(p)])
    elif IS_MAC:
        _popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
    else:
        open_path(p if p.is_dir() else p.parent)


def open_url(url: str):
    if url.startswith("https://"):
        import webbrowser
        webbrowser.open(url)


# ---------------- portapapeles ----------------
def copy_text(text: str) -> bool:
    try:
        if IS_MAC:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                           env={**os.environ, "LANG": "en_US.UTF-8"})
            return True
        if IS_WIN:
            # clip.exe necesita UTF-16 para tildes y emojis
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return True
            except Exception:
                continue
    except Exception:
        pass
    try:  # último recurso
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


# ---------------- nombres de carpeta válidos ----------------
_WIN_BAD = '<>:"/\\|?*'
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name: str) -> str:
    """Nombre de playlist -> nombre de carpeta válido (más estricto en Windows)."""
    name = (name or "").replace("/", "_").replace(":", "_")
    if IS_WIN:
        name = "".join("_" if c in _WIN_BAD or ord(c) < 32 else c for c in name)
        name = name.rstrip(" .")
        if name.upper().split(".")[0] in _WIN_RESERVED:
            name = "_" + name
    name = name.strip().lstrip(".")
    return name or "Sin nombre"


def migrate_launcher(log=print):
    """La app antes se llamaba SpotiSync: renombra su ícono/accesos directos a BrainOrder.
    Mac: SpotiSync.app -> BrainOrder.app (con su lanzador nuevo). Windows: SpotiSync.lnk -> BrainOrder.lnk.
    No toca la carpeta de datos (eso lo hace el instalador). Seguro de repetir."""
    import shutil
    try:
        if IS_MAC:
            import plistlib
            bundle = os.environ.get("BRAINORDER_BUNDLE") or os.environ.get("SPOTISYNC_BUNDLE")
            if not bundle or not bundle.endswith("SpotiSync.app") or not Path(bundle).is_dir():
                return None
            old = Path(bundle)
            new = old.with_name("BrainOrder.app")
            if new.exists():
                return None
            plist = old / "Contents" / "Info.plist"
            info = plistlib.loads(plist.read_bytes())
            info.update(CFBundleName="BrainOrder", CFBundleDisplayName="BrainOrder",
                        CFBundleIdentifier="com.brainwasher.brainorder", CFBundleExecutable="BrainOrder")
            launcher = support_dir() / "app" / "mac" / "lanzador.sh"
            exe_dir = old / "Contents" / "MacOS"
            if launcher.exists():
                shutil.copy2(launcher, exe_dir / "BrainOrder")
            else:
                shutil.copy2(exe_dir / "SpotiSync", exe_dir / "BrainOrder")
            os.chmod(exe_dir / "BrainOrder", 0o755)
            plist.write_bytes(plistlib.dumps(info))
            try:
                (exe_dir / "SpotiSync").unlink()
            except OSError:
                pass
            os.rename(old, new)
            os.utime(new, None)
            subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/"
                            "Support/lsregister", "-f", str(new)], capture_output=True, timeout=20)
            os.environ["BRAINORDER_BUNDLE"] = str(new)
            log(f"app renombrada: {old} -> {new}")
            return str(new)
        if IS_WIN:
            done = []
            for d in (HOME / "Desktop", Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"):
                o, n = d / "SpotiSync.lnk", d / "BrainOrder.lnk"
                if o.exists() and not n.exists():
                    os.rename(o, n)
                    done.append(str(n))
            if done:
                log(f"accesos directos renombrados: {done}")
            return done or None
    except Exception as e:
        log(f"no pude renombrar la app a BrainOrder: {e!r}")
    return None


# ---------------- nombre e ícono en macOS ----------------
def mac_branding(name="BrainOrder", icon=None):
    """Que la barra de menú (junto a la manzana), el Dock y ⌘-Tab digan BrainOrder y no «Python».

    Python corre dentro de Python.app, así que macOS toma ese nombre. Se cambia el nombre del bundle en
    memoria ANTES de crear la ventana (macOS lo lee al arrancar la app) y se pone el ícono de BrainOrder.
    El lanzador nuevo además arranca Python desde dentro de BrainOrder.app (ver mac/lanzador.sh)."""
    if not IS_MAC:
        return False
    try:
        from Foundation import NSBundle, NSProcessInfo
        b = NSBundle.mainBundle()
        for d in (b.infoDictionary(), b.localizedInfoDictionary()):
            if d is None:
                continue
            try:  # en la práctica es un diccionario modificable (truco que usan rumps y py2app)
                d["CFBundleName"] = name
                d["CFBundleDisplayName"] = name
            except Exception:
                pass
        NSProcessInfo.processInfo().setProcessName_(name)
    except Exception:
        return False
    if icon and Path(icon).exists():
        try:
            from AppKit import NSApplication, NSImage
            img = NSImage.alloc().initByReferencingFile_(str(icon))
            if img is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
        except Exception:
            pass
    return True


def refresh_launcher(log=print):
    """Las actualizaciones automáticas cambian el código pero no el lanzador que está dentro de
    BrainOrder.app: si cambió, se copia el nuevo (se usa desde la próxima vez que se abra)."""
    if not IS_MAC:
        return False
    import filecmp
    import shutil
    bundle = os.environ.get("BRAINORDER_BUNDLE")
    if not bundle or not bundle.endswith(".app"):
        return False
    exe = Path(bundle) / "Contents" / "MacOS" / "BrainOrder"
    new = support_dir() / "app" / "mac" / "lanzador.sh"
    try:
        if exe.is_file() and new.is_file() and not filecmp.cmp(exe, new, shallow=False):
            tmp = exe.with_name(".BrainOrder.new")
            shutil.copy2(new, tmp)
            os.chmod(tmp, 0o755)
            os.replace(tmp, exe)
            log("lanzador de BrainOrder.app actualizado")
            return True
    except Exception as e:
        log(f"no pude actualizar el lanzador: {e!r}")
    return False


# ---------------- mover archivos sin riesgo ----------------
def safe_move(src, dst):
    """Mueve un archivo sin que nunca quede una copia a medias.

    - Mismo disco: renombrar (instantáneo y atómico).
    - Otro disco: se copia a un temporal oculto junto al destino, se comprueba el tamaño, se
      renombra al nombre final y solo entonces se borra el original. Si algo falla (disco lleno,
      se desconectó el disco…) se borra el temporal y el original queda intacto.
    Nunca pisa un archivo existente en el destino."""
    import errno
    import shutil
    src, dst = str(src), str(dst)
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "Ya existe un archivo con ese nombre en el destino", dst)
    try:
        os.rename(src, dst)  # en Windows os.rename no pisa; en Mac ya comprobamos que no existe
        return dst
    except OSError as e:
        if e.errno not in (errno.EXDEV, getattr(errno, "ENOTSUP", -1)) and not (IS_WIN and getattr(e, "winerror", 0) == 17):
            raise
    d = Path(dst)
    tmp = d.with_name(f".{d.name}.brainorder-partial")
    try:
        shutil.copy2(src, tmp)
        if os.path.getsize(tmp) != os.path.getsize(src):
            raise OSError(errno.EIO, "La copia quedó incompleta", dst)
        if os.path.lexists(dst):
            raise FileExistsError(errno.EEXIST, "Ya existe un archivo con ese nombre en el destino", dst)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.unlink(src)
    except OSError:
        # no se pudo borrar el original: se deja como estaba (sin duplicar) y se avisa
        try:
            os.unlink(dst)
        except OSError:
            pass
        raise
    return dst


# ---------------- programas abiertos (una sola consulta para todos) ----------------
_PROCS = {"t": 0.0, "list": None}
_PROCS_TTL = 2.5


def processes():
    """Nombres/rutas de los procesos abiertos. Se consulta una vez cada 2,5 s como máximo y lo
    comparten todos los chequeos («¿Rekordbox/Traktor/Serato/Engine está abierto?»). En Windows
    tasklist tarda casi un segundo: antes se llamaba una vez por programa."""
    import threading
    import time
    lock = _PROCS.setdefault("lock", threading.Lock())
    with lock:
        if _PROCS["list"] is not None and time.time() - _PROCS["t"] < _PROCS_TTL:
            return _PROCS["list"]
        out = []
        try:
            if IS_WIN:
                r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                out = [line.split('","')[0].strip('"') for line in r.stdout.splitlines() if line.strip()]
            else:
                r = subprocess.run(["ps", "-axo", "comm"], capture_output=True, text=True, timeout=5)
                out = [line.strip() for line in r.stdout.splitlines()[1:] if line.strip()]
        except Exception:
            out = None
        _PROCS["list"], _PROCS["t"] = out, time.time()
        return out


def any_process(pred):
    """True si algún proceso abierto cumple pred(nombre_o_ruta). None si no se pudo consultar."""
    procs = processes()
    if procs is None:
        return None
    return any(pred(p) for p in procs)


def mik_app():
    """Dónde está Mixed In Key (la versión más nueva instalada) o None."""
    import glob
    import re as _re
    if IS_MAC:
        cands = glob.glob("/Applications/Mixed In Key*.app") + glob.glob(str(Path.home() / "Applications" / "Mixed In Key*.app"))
    elif IS_WIN:
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        cands = [p for r in roots for p in glob.glob(os.path.join(r, "Mixed In Key*", "**", "*.exe"), recursive=True)
                 if "uninst" not in os.path.basename(p).lower() and "mixed" in os.path.basename(p).lower()]
    else:
        cands = []
    if not cands:
        return None
    ver = lambda p: [int(x) for x in _re.findall(r"\d+", os.path.basename(p))] or [0]
    return max(cands, key=ver)


def open_with_mik(paths, app=None):
    """Abre esos archivos con Mixed In Key (quedan en su lista para analizar). -> cuántos se mandaron"""
    app = app or mik_app()
    if not app:
        raise FileNotFoundError("Mixed In Key")
    paths = [str(p) for p in paths if os.path.isfile(p)]
    for i in range(0, len(paths), 100):  # de a 100 para no pasar el límite de argumentos
        chunk = paths[i:i + 100]
        if IS_MAC:
            subprocess.run(["open", "-a", app] + chunk, check=True, timeout=60)
        else:
            subprocess.Popen([app] + chunk)
    return len(paths)
