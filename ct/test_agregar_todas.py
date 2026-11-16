"""2.53.0: las playlists de Rekordbox sin música nueva SÍ quedan en BrainOrder, «Agregar todas» con su carpeta de
Rekordbox como grupo, y las que antes se marcaban «agregadas» sin crearse vuelven a salir."""
import os
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

LISTS = {"10": {"name": "Salsa vieja", "paths": ["/m/a.mp3"], "folder": "Crossover / MGNO"},
         "11": {"name": "Sueltita", "paths": ["/m/b.mp3"], "folder": ""},
         "12": {"name": "Con nuevas", "paths": ["/x/c.mp3"], "folder": "Electronica Hard"}}
DJ.read = lambda cfg, program: LISTS
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "dj_import_all")][0]
o = A.__new__(A)
o._cfg = {"pl_groups": {}, "groups_folders": True}
o._progress = lambda *a, **k: None
o._set_stage = lambda *a: None
o._state = app.threading.RLock()
o._an = [{"id": "x", "name": "Ya existe"}]
o._analysis = lambda: o._an
o._build_analysis = lambda light=True: o._an
o._task = lambda fn, key, label, files=False: {"ok": True, **fn()}
o._dj_novelty = lambda name, paths, lib=None: {"existing": None, "new": ["/x/c.mp3"] if name == "Con nuevas" else []}
o._nov_summary = lambda nov: {}
o._nov_files = lambda nov: list(nov["new"])
IMP = []


def imp(name, files, opts, entry, pid, src_folder=None):
    IMP.append((name, files, opts, entry))
    o._an.append({"id": pid, "name": name})
    return {"pid": pid, "result": {"name": name, "files": len(files)}}


o._import_playlist = imp
ADOPT = []
o._rb_adopt_add = lambda jobs: ADOPT.extend(jobs)
o._rb_adopt_run = lambda interactive=False: ADOPT.append("run") or {}
o._grp_rb_run = lambda interactive=False: None
app.rekordbox_sync.rekordbox_running = lambda: False
o._grp_queue = lambda before, after: 0

# una sola, sin nada nuevo: ya NO se marca «agregada» sin crearla
r = o.dj_import("rekordbox", "11", {})
assert r["ok"] and IMP[-1][0] == "Sueltita" and IMP[-1][1] == [] and IMP[-1][2]["move"] is False, IMP
assert r["result"]["nothing_new"] and r["result"]["adopt"]["mode"] == "move", r
IMP.clear()
ADOPT.clear()
CN.dj_undismiss("rekordbox", "11")

# todas: su carpeta de Rekordbox como grupo y las originales se mueven UNA vez al final
r = o.dj_import_all("rekordbox", ["10", "11", "12", "99"], {"keep_folder": True})
res = r["result"]
assert res["total"] == 3 and len(res["done"]) == 3 and not res["errors"], res
g = o._cfg["pl_groups"]
pid = lambda ref: app.fuentes.carpetas.dj_pid("rekordbox", ref) if hasattr(app.fuentes, "carpetas") else None
from fuentes import carpetas as FC  # noqa: E402
assert g[FC.dj_pid("rekordbox", "10")] == "Crossover / MGNO" and g[FC.dj_pid("rekordbox", "12")] == "Electronica Hard", g
assert FC.dj_pid("rekordbox", "11") not in g  # sin carpeta: sin grupo («Organizar»)
assert [a for a in ADOPT if a == "run"] == ["run"] and len([a for a in ADOPT if a != "run"]) == 3, ADOPT
assert [i[1] for i in IMP] == [[], [], ["/x/c.mp3"]], IMP
print("agregar todas ok")

# las que antes se marcaban «agregadas» sin crearse vuelven a salir; las que sí existen (por nombre) no
st = CN.load()
o._imported_dj_keys = lambda: set()
o._an = [{"id": "x", "name": "Salsa vieja"}]
app.destinos.DESTINATIONS["rekordbox"].available = lambda cfg: True
o._rb_adopt_candidates = lambda lists=None: []
import novedades  # noqa: E402
novedades.Biblioteca = lambda an: None
r = o.rb_outside()
names = {i["name"]: i["state"] for i in r["items"]}
assert "Salsa vieja" not in names and names.get("Sueltita") == "new" and names.get("Con nuevas") == "new", names
print("perdidas vuelven ok")
print("OK")
