"""Vaciar _duplicados: a la Papelera solo lo que tiene otra copia y no usa ningún programa de DJ."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import config
TMP = Path(tempfile.mkdtemp()); config.SUPPORT_DIR = TMP; config.LOG_FILE = TMP / "log.txt"
config.save = lambda c: None
import app, accesos, historial, biblioteca, dj_playlists
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'dup_rescue')][0]
root = TMP / "BRAIN LIBRARY"; inbox = TMP / "descargas"
(root / "Techno").mkdir(parents=True); (inbox / "_duplicados" / "Techno").mkdir(parents=True)
def mk(p, data): p.write_bytes(data); return str(p)
mk(root / "Techno" / "Uno.mp3", b"1" * 2000)
mk(root / "Techno" / "Dos.mp3", b"2" * 2000)
ok = mk(inbox / "_duplicados" / "Techno" / "Uno.mp3", b"1" * 2000)        # copia idéntica -> Papelera
used = mk(inbox / "_duplicados" / "Dos.mp3", b"2" * 2000)                # Rekordbox la usa -> no
only = mk(inbox / "_duplicados" / "Tres.mp3", b"3" * 2000)               # única copia -> no
o = A.__new__(A); o._cfg = {"dest_root": str(root), "inbox": str(inbox)}
o._analysis = lambda: []
o._task = lambda fn, k, l, files=False: fn()
o._progress = lambda *a, **k: None
o._rb_track_paths = lambda: [used]
historial.all_ops = lambda: []
dj_playlists.enabled_programs = lambda cfg: []
trash = []
accesos.to_trash = lambda ps, label=None: [trash.append(p) or (p, "papelera") for p in ps]
r = o.dup_clean_scan()
st = {Path(x["path"]).name: x["state"] for x in r["items"]}
assert st == {"Uno.mp3": "ok", "Dos.mp3": "used", "Tres.mp3": "only"}, st
assert (r["ok"], r["used"], r["only"], r["bytes"]) == (1, 1, 1, 2000), r
# aunque la ventana pida las tres, solo va la que tiene otra copia
r = o.dup_clean([ok, used, only])
assert trash == [ok] and r["trashed"] == 1 and r["skipped"] == 2, (trash, r)
print("ok")
