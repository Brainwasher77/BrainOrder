"""Perdidas en Rekordbox, «Otra versión»: no se repara sola, pero si eliges «unir» o «sacarla» se hace."""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app, config, rekordbox_sync, rb_perdidas, rb_coleccion, rb_cambios, historial
config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'rb_lost_replace')][0]
SCAN = [{"id": "1", "kind": "version", "state": "lost", "action": None, "path": "/T/El Matador.mp3",
         "copy": {"id": "9", "path": "/M/El Matador.mp3", "in_collection": True}},
        {"id": "2", "kind": "sin", "state": "lost", "action": None, "path": "/x.mp3", "copy": None},
        {"id": "3", "kind": "exacta", "state": "lost", "action": "relink", "path": "/y.mp3", "copy": {"id": None, "path": "/z.mp3"}}]
got = {}
o = A.__new__(A); o._cfg = {}
o._rb_lost_scan = lambda: {"items": [dict(x) for x in SCAN]}
o._task = lambda fn, k, l, files=False: fn()
o._progress = lambda *a, **k: None
rekordbox_sync.rekordbox_running = lambda: False
rekordbox_sync.backup = lambda: types.SimpleNamespace(name="bk.db")
class DB:
    def __init__(self, path): pass
    def commit(self): pass
    def close(self): pass
import pyrekordbox
pyrekordbox.MasterDatabase = DB
rb_perdidas.apply = lambda db, items, remove, prog: (got.update(items=items, remove=remove) or ({"relinked": 0, "merged": 0, "removed": 0, "skipped": 0}, [], [], {}))
rb_perdidas.log_result = lambda *a: None
rb_coleccion.write_anlz = lambda a: None
historial.record_rb = lambda *a, **k: "op"
# sin elegir nada: la «Otra versión» no se toca
o.rb_lost_replace(["1", "3"], [])
assert [x["id"] for x in got["items"]] == ["3"], got
# elegiste unir: entra como «merge» con su copia de la colección
o.rb_lost_replace(["3"], [], ["1"])
assert {x["id"]: x["action"] for x in got["items"]} == {"1": "merge", "3": "relink"}, got
# elegiste sacarla de la colección
o.rb_lost_replace([], ["1"], [])
assert got["remove"] == ["1"] and not got["items"], got
print("OK")
