"""Playlists de Rekordbox fuera de la carpeta de BrainOrder: se listan TODAS (también las de antes), y al
agregarlas eliges nombre, a cuál sumarlas y en qué grupo."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
config.save = lambda c: None
import app  # noqa: E402
import carpetas_nuevas as CN  # noqa: E402
import dj_playlists as DJ  # noqa: E402

CN.STATE = TMP / "carpetas.json"
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "rb_outside")][0]
lists = {"11": {"name": "Boda Ana", "folder": "Eventos", "paths": ["/m/1.mp3", "/m/2.mp3"]},
         "12": {"name": "Vieja", "folder": "", "paths": ["/m/3.mp3"]},
         "13": {"name": "Importada", "folder": "", "paths": []},
         "14": {"name": "Descartada", "folder": "", "paths": []},
         "15": {"name": "Recién creada", "folder": "", "paths": []}}
DJ.read = lambda cfg, prog: lists
CN.dj_baseline("rekordbox", {"11": 0, "12": 0, "13": 0, "14": 0})  # las que ya existían antes de BrainOrder
CN.dj_mark("rekordbox", "14", dismissed=True)
o = A.__new__(A)
o._cfg = {"folder_playlists": [{"name": "Importada", "program": "rekordbox", "ref": "13"}], "pl_groups": {}}
o._task = lambda fn, k, l, files=False: {"ok": True, **fn()}
o._progress = lambda *a, **k: None
ana = [{"id": "sp1", "name": "Salsa", "source": "spotify", "tracks": []}]
o._analysis = lambda: ana
o._dj_novelty = lambda name, paths, lib=None: {"new": list(paths), "have": [], "missing": 0,
                                                "existing": {"id": "sp1", "name": "Salsa", "source": "spotify"} if name == "Salsa" else None}
app.destinos.DESTINATIONS["rekordbox"].available = lambda cfg: True
import novedades  # noqa: E402

novedades.Biblioteca = lambda a: None
r = o.rb_outside()
st = {x["ref"]: x["state"] for x in r["items"]}
print(st)
# las de antes ya no quedan escondidas; la importada no sale; la descartada sale como «no agregada»
assert st == {"11": "old", "12": "old", "14": "dismissed", "15": "new"}, st
assert next(x for x in r["items"] if x["ref"] == "11")["folder"] == "Eventos"

calls = []
o._dj_add_to_existing = lambda nov, opts: (calls.append(("add", nov["existing"]["id"], opts)), {"result": {}, "pid": nov["existing"]["id"]})[1]
o._import_playlist = lambda name, files, opts, entry, pid, src_folder=None: (calls.append(("new", name, entry)), {"result": {}, "pid": pid})[1]
# sumarla a la que elegiste (aunque se llame distinto) y ponerla en un grupo
o.dj_import("rekordbox", "11", {"into": "sp1", "group": "Eventos"})
assert calls[-1][:2] == ("add", "sp1"), calls
assert o._cfg["pl_groups"] == {"sp1": "Eventos"}
# como playlist nueva con otro nombre
o.dj_import("rekordbox", "12", {"name": "  Vieja   pero buena "})
assert calls[-1][:2] == ("new", "Vieja pero buena") and calls[-1][2]["name"] == "Vieja pero buena", calls[-1]
# ya pasadas: no vuelven a aparecer en la lista
r = o.rb_outside()
assert {x["ref"] for x in r["items"]} == {"14", "15"}, r["items"]
# volver a mostrar una descartada
o._fold_told = set()
o.dj_undismiss("rekordbox", "14")
assert {x["ref"]: x["state"] for x in o.rb_outside()["items"]}["14"] == "old"
shutil.rmtree(TMP)
print("OK")
