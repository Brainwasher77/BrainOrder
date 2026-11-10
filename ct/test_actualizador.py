"""El actualizador solo instala un paquete que sea BrainOrder, de la versión anunciada, completo y con
código que compile; no acepta rutas raras, enlaces ni descargas de otros sitios."""
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
config.LOG_FILE = TMP / "brainorder.log"
import actualizador as U  # noqa: E402

U.SUPPORT_DIR = TMP
U.UPDATE = TMP / "update"
U.installed_layout = lambda: True
U.local_version = lambda: {"version": "1.0.0", "build": 10}


def pkg(build=11, files=None, extra=None):
    base = {"app.py": "x = 1\n", "arranque.py": "y = 2\n", "ui.html": "<html></html>", "config.py": "z = 3\n",
            "version.json": json.dumps({"version": "1.1.0", "build": build, "notes": "n"})}
    base.update(files or {})
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in base.items():
            if v is not None:
                z.writestr("BrainOrder-main/" + k, v)
        for info, data in extra or []:
            z.writestr(info, data)
    return b.getvalue()


def run(zip_bytes, remote_build=11):
    U._remote_version = lambda timeout=8: {"version": "1.1.0", "build": remote_build, "notes": "aviso"}
    U._get = lambda url, timeout=15, limit=0: zip_bytes
    return U.check_and_download()


# 1. paquete bueno -> listo, con la info del paquete
r = run(pkg())
assert r["status"] == "ready" and r["new"]["build"] == 11, r
assert (U.UPDATE / "app" / "app.py").is_file() and json.loads((U.UPDATE / "ready.json").read_text())["build"] == 11
# ya descargada: no se vuelve a bajar
U._get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debía descargar"))
U._remote_version = lambda timeout=8: {"version": "1.1.0", "build": 11}
assert U.check_and_download()["status"] == "ready"

bad = {
    "paquete viejo (GitHub a medio publicar)": pkg(build=10),
    "código que no compila": pkg(files={"app.py": "def roto(:\n"}),
    "le falta la ventana": pkg(files={"ui.html": None}),
    "version.json ilegible": pkg(files={"version.json": "{"}),
    "ruta que se sale": pkg(extra=[("../fuera.py", "x")]),
    "ruta absoluta": pkg(extra=[("/tmp/fuera.py", "x")]),
    "no es un zip": b"<html>error</html>",
}
ln = zipfile.ZipInfo("BrainOrder-main/enlace")
ln.external_attr = 0o120777 << 16
bad["trae un enlace"] = pkg(extra=[(ln, "/etc/passwd")])
for why, z in bad.items():
    import shutil
    shutil.rmtree(U.UPDATE, ignore_errors=True)
    r = run(z)
    assert r["status"] == "error", (why, r)
    assert not U.UPDATE.exists(), f"{why}: quedó algo descargado"
    assert not (TMP.parent / "fuera.py").exists()

# 2. solo GitHub por HTTPS
for url in ("http://raw.githubusercontent.com/x", "https://evil.example/x", "file:///etc/passwd",
            "https://raw.githubusercontent.com.evil.example/x"):
    try:
        U._check_url(url)
        raise SystemExit(f"aceptó {url}")
    except RuntimeError:
        pass
U._check_url("https://codeload.github.com/Brainwasher77/BrainOrder/zip/refs/heads/main")
print("OK")
