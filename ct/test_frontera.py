"""La frontera con la ventana: mismos métodos y parámetros que Api, y un error inesperado vuelve como
{ok: False, error} en vez de dejar a la ventana esperando. También: una sola BrainOrder abierta a la vez."""
import inspect
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
config.LOG_FILE = TMP / "brainorder.log"
config.save = lambda c: None
import app  # noqa: E402
import instancia  # noqa: E402

A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "rb_outside")][0]
o = A.__new__(A)
o._cfg = {}
import threading  # noqa: E402

o._files = threading.Lock()
f = app._front(o)
pub = sorted(n for n in dir(A) if not n.startswith("_") and callable(getattr(A, n)))
assert sorted(n for n in dir(f) if not n.startswith("_")) == pub, "la ventana ve otros métodos"
for n in pub:  # mismos parámetros (pywebview les quita el primero, self)
    assert inspect.getfullargspec(getattr(f, n)).args[1:] == inspect.getfullargspec(getattr(o, n)).args[1:], n
    assert inspect.ismethod(getattr(f, n))
# error inesperado -> respuesta ordenada y registro
r = f.save_settings(None)
assert r["ok"] is False and "inesperado" in r["error"], r
assert "save_settings: error inesperado" in config.LOG_FILE.read_text("utf-8")
# lo que funciona pasa tal cual
assert f.platform() == o.platform()
# por dentro Api no cambia: el error sigue saliendo como excepción
try:
    o.save_settings(None)
    raise SystemExit("Api.save_settings debería fallar")
except AttributeError:
    pass

# reiniciar / cerrar no cortan un movimiento de archivos
assert o._busy_with_files() is False
o._files.acquire()
assert o._busy_with_files() is True
r = o.restart()
assert r["ok"] is False and "moviendo archivos" in r["error"], r
o._files.release()

# una sola copia abierta
lock = TMP / "brainorder.lock"
assert instancia.acquire(lock) is True
assert instancia.acquire(lock) is True  # la misma copia puede preguntar dos veces
code = ("import sys; sys.path.insert(0, %r); import instancia; "
        "sys.exit(0 if instancia.acquire(%r) else 7)") % (str(Path(app.__file__).parent), str(lock))
assert subprocess.run([sys.executable, "-c", code]).returncode == 7, "otra copia pudo abrirse"
instancia.release(lock)
assert subprocess.run([sys.executable, "-c", code]).returncode == 0, "el candado no se soltó"
print("OK")
