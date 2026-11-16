"""Playlist de carpeta con la misma canción dos veces: una fila es el archivo de la carpeta y la otra un archivo
que la playlist RECUERDA (se movió a _Sin Playlist) y se ve con el mismo archivo. «Quitar las de más» tiene que
olvidar ese recuerdo; antes no lo hacía (se buscaba por archivo, y ese archivo lo sigue usando la otra) y la
repetida volvía a salir."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import app, config
config.save = lambda c: None
from fuentes import carpetas as FC
root = Path(tempfile.mkdtemp())
fold, sinp = root / "HOUSE CLASSICS", root / "_Sin Playlist"
fold.mkdir(); sinp.mkdir()
keep = fold / "Room 5 - Make Luv.mp3"; keep.write_bytes(b"1" * 900)
old = sinp / "Room 5 Feat. Oliver Cheatham - Make Luv (Radio Version).mp3"; old.write_bytes(b"2" * 900)
mem = {"dir:x": [str(keep), str(fold / old.name)]}  # recuerda la ruta vieja (ya no está en la carpeta)
FC.members = lambda pid: list(mem.get(pid) or [])
FC.forget = lambda pid, paths: mem.__setitem__(pid, [m for m in mem.get(pid) or [] if m not in set(paths)])
rows = [{"pos": 0, "id": FC.track_id(str(keep)), "name": "Make Luv", "source": str(keep)},
        {"pos": 1, "id": FC.track_id(str(fold / old.name)), "name": "Make Luv (Radio Version)", "source": str(keep)}]
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'playlist_tracks_move')][0]
PL = {"dir:x": {"id": "dir:x", "name": "HOUSE CLASSICS", "folder": str(fold), "tracks": rows}}
o = A.__new__(A); o._cfg = {"dest_root": str(root)}
o._analysis = lambda: list(PL.values())
o._pl_ctx = lambda pid, an=None: (PL[pid], 'carpetas', {"path": str(fold)}, str(fold))
o._pl_can_remove = lambda *a: True
o._rb_ref = lambda *a: None
o._rb_ready = lambda *a: None
o._set_stage = lambda *a: None
o._task = lambda fn, k, l, files=False: fn()
o._build_analysis = lambda light=True: list(PL.values())
o._relocate_ops = lambda ops, label, extra=None: {"moved": 0, "changes": {}}
FC.list_playlists = lambda cfg: []
r = o.playlist_tracks_move('dir:x', [1], None)
assert mem["dir:x"] == [str(keep)], mem          # el recuerdo de la Radio Version se olvidó
assert keep.exists() and old.exists()             # ningún archivo se tocó
assert r["result"].get("shared") == 1
# 2.57.7: quitar la otra (la del archivo de la carpeta) también olvida el recuerdo: el archivo sigue en la carpeta
# y la playlist lo vuelve a leer igual, así que si se olvidaba el archivo las dos volvían a salir
mem["dir:x"] = [str(keep), str(fold / old.name)]
o.playlist_tracks_move('dir:x', [0], None)
assert mem["dir:x"] == [str(keep)], mem
print("OK")
