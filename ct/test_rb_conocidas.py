"""«Cambios en Rekordbox»: las playlists que ya son de BrainOrder no salen para siempre como «Creaste la playlist»."""
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
import rb_cambios  # noqa: E402

rb_cambios.BASELINE = TMP / "rb_baseline.json"
rb_cambios.FOUND.update(name="BRAINLIBRARY", renamed=False)

A = app.Api
o = A.__new__(A)
o._cfg = {"folder_playlists": [{"name": "Dancehall", "program": "rekordbox", "ref": "40"}]}
ana = [{"id": "sp1", "name": "Jungle House", "source": "spotify"},
       {"id": "dir:x", "name": "Desembale", "source": "carpetas"},
       {"id": "placeholder", "name": "Dancehall", "source": "carpetas"},
       {"id": "sp2", "name": "Techno", "source": "spotify"}]
from fuentes import carpetas as FC  # noqa: E402
ana[2]["id"] = FC.entry_pid(o._cfg["folder_playlists"][0])

rb_cambios.save_baseline({"10": {"pid": "sp2", "name": "Techno", "paths": ["/m/t1.mp3"]}})
state = {
    "10": {"name": "Techno", "folder": [], "paths": ["/m/t1.mp3"]},
    "20": {"name": "Jungle House", "folder": ["House"], "paths": []},             # vacía repetida
    "21": {"name": "Jungle House", "folder": ["House"], "paths": ["/m/j1.mp3", "/m/j2.mp3"]},
    "30": {"name": "desembale", "folder": ["Organizar"], "paths": ["/m/d1.mp3"]},  # mismo nombre (sin mayúsculas)
    "40": {"name": "Dancehall", "folder": ["Organizar"], "paths": ["/m/x.mp3"]},  # agregada desde Rekordbox
    "50": {"name": "Axé", "folder": ["Organizar"], "paths": ["/m/a.mp3"]},        # nueva de verdad
}
n = o._rb_link_known(state, ana)
assert n == 3, n
base = rb_cambios.load_baseline()
assert base["21"]["pid"] == "sp1" and "20" not in base, base
assert base["30"]["pid"] == "dir:x"
assert base["40"]["pid"] == ana[2]["id"]
ch = rb_cambios.diff(base, state, ana)
created = sorted(c["rb_id"] for c in ch if c["type"] == "created")
assert created == ["20", "50"], ch
# otra vuelta: nada nuevo
assert o._rb_link_known(state, ana) == 0
print("OK test_rb_conocidas")
