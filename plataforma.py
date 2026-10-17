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
