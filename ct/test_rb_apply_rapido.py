"""2.50.2: corregir rutas en Rekordbox con miles de canciones sin recorrer la colección por cada una."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rb_coleccion as RC  # noqa: E402
import rekordbox_sync  # noqa: E402
import unificar  # noqa: E402

N = 20000


class C:
    def __init__(self, i, p):
        self.ID, self.FolderPath, self.OrgFolderPath, self.FileNameL, self.FileSize = i, p, p, p.rsplit("/", 1)[-1], 1


ST = {"q": 0, "commit": 0, "anlz": 0}


class DB:
    def __init__(self, path=None):
        self.cs = ST["cs"]

    def get_content(self, FolderPath=None, **k):
        ST["q"] += 1
        return [c for c in self.cs if FolderPath is None or c.FolderPath == FolderPath]

    def read_anlz_files(self, i):
        ST["anlz"] += 1
        return {}

    def get_anlz_dir(self, c):
        return Path("/no/existe")

    def commit(self):
        ST["commit"] += 1

    def rollback(self):
        pass

    def close(self):
        pass


import pyrekordbox  # noqa: E402
pyrekordbox.MasterDatabase = DB
merged = []
RC.merge = lambda db, lost, keep, undo: merged.append((lost.ID, keep.ID))
os.path.islink = lambda p: False
ST["cs"] = [C(i, f"/Users/f/Music/Viejo/t{i}.mp3") for i in range(N)]
ST["cs"][5].FolderPath = "//Users/f/Music/Viejo/t5.mp3"            # barras de más
ST["cs"].append(C("ya", "/Users/f/Music/Nuevo/t7.mp3"))            # ya hay una pista en el destino de t7
change = {f"/Users/f/Music/Viejo/t{i}.mp3": f"/Users/f/Music/Nuevo/t{i}.mp3" for i in range(N)}
seen = []
t0 = time.time()
st = unificar._rb_apply(change, {}, {}, lambda txt, f=None: seen.append(txt))
dt = time.time() - t0
assert ST["q"] <= 2, ST  # la colección se lee una vez (antes: 2-3 búsquedas por canción)
assert st["paths"] == N - 1 and st["merged"] == 1 and merged == [(7, "ya")], (st, merged)
assert ST["cs"][5].FolderPath == "/Users/f/Music/Nuevo/t5.mp3" and ST["cs"][100].FileNameL == "t100.mp3"
assert ST["cs"][100].FolderPath.endswith("Nuevo/t100.mp3") and ST["commit"] == 1
rutas = [x for x in seen if x.startswith("Corrigiendo rutas")]
assert any("20000/20000" in x for x in rutas) and len(rutas) < 100, rutas[-3:]
assert ST["anlz"] == 0, "no se deben interpretar los ANLZ enteros"
assert dt < 30, dt
print(f"{N} canciones en {dt:.1f} s")
print("OK")
