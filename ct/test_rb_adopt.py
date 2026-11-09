"""La playlist original de Rekordbox pasa a la carpeta de BrainOrder al agregarla (no queda dos veces)."""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
config.save = lambda c: None
import app  # noqa: E402
import dj_playlists as DJ  # noqa: E402
import rb_cambios  # noqa: E402
import rekordbox_sync as RS  # noqa: E402

rb_cambios.BASELINE = TMP / "rb_baseline.json"


class Content:
    def __init__(self, i, path):
        self.ID, self.FolderPath = i, path


class Song:
    def __init__(self, c, n):
        self.Content, self.ContentID, self.TrackNo = c, c.ID, n


class PL:
    def __init__(self, i, name, parent, attr=0):
        self.ID, self.Name, self.ParentID, self.Attribute, self.Songs = i, name, parent, attr, []


class Q(list):
    def first(self):
        return self[0] if self else None


class FakeDB:
    def __init__(self, *a, **k):
        self.pls = ST["pls"]

    def get_playlist(self, ID=None, ParentID=None, Name=None):
        if ID is not None:
            return next((p for p in self.pls if str(p.ID) == str(ID)), None)
        if ParentID is None and Name is None:
            return Q(self.pls)  # como pyrekordbox: sin filtros, todas
        return Q([p for p in self.pls if p.ParentID == ParentID and p.Name == Name])

    def create_playlist_folder(self, name):
        p = PL("F", name, "root", 1)
        self.pls.append(p)
        return p

    def move_playlist(self, pl, parent=None):
        pl.ParentID = parent.ID

    def rename_playlist(self, pl, name):
        pl.Name = name

    def delete_playlist(self, pl):
        self.pls.remove(pl)

    def add_to_playlist(self, pl, c):
        pl.Songs.append(Song(c, len(pl.Songs) + 1))

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


import pyrekordbox  # noqa: E402

pyrekordbox.MasterDatabase = FakeDB
RS.backup = lambda: Path("/tmp/x.db")
RUNNING = [False]
RS.rekordbox_running = lambda: RUNNING[0]
c = {k: Content(k, f"/m/{k}.mp3") for k in "abcd"}


def pl(i, name, parent, songs):
    p = PL(i, name, parent)
    for n, k in enumerate(songs, 1):
        p.Songs.append(Song(c[k], n))
    return p


folder = PL("1", "BrainOrder", "root", 1)
ST = {"pls": [folder, pl("10", "Boda Ana", "ev", "ab"), pl("11", "Salsa vieja", "root", "c"),
              pl("12", "Techno", "root", "cd"), pl("13", "Techno", "1", "c")]}
cfg = {"rekordbox_folder": "BrainOrder"}
r = RS.adopt(cfg, [{"ref": "10", "pid": "sp1", "name": "Boda Ana 2025", "mode": "move"},  # nueva con otro nombre
                   {"ref": "11", "pid": "sp2", "name": "Salsa", "mode": "delete"},       # la sumaste a «Salsa»
                   {"ref": "12", "pid": "sp3", "name": "Techno", "mode": "move"},        # ya hay una «Techno» en la carpeta
                   {"ref": "99", "pid": "x", "name": "Borrada", "mode": "move"}])        # ya no existe
names = {(p.ParentID, p.Name) for p in ST["pls"]}
print(r["moved"], r["merged"], r["deleted"], r["missing"], sorted(names))
assert ("1", "Boda Ana 2025") in names and ("ev", "Boda Ana") not in names
assert not any(p.Name == "Salsa vieja" for p in ST["pls"])
techno = [p for p in ST["pls"] if p.Name == "Techno"]
assert len(techno) == 1 and techno[0].ParentID == "1" and [s.ContentID for s in techno[0].Songs] == ["c", "d"]
assert (r["moved"], r["merged"], r["deleted"], r["missing"]) == (1, 1, 1, 1)
assert r["baseline"]["10"]["paths"] == ["/m/a.mp3", "/m/b.mp3"] and r["baseline"]["10"]["pid"] == "sp1"
assert len(r["done"]) == 4
print("adopt ok")

# ---------------- la importada sin plataforma sigue leyéndose aunque ahora esté dentro de la carpeta
db = sqlite3.connect(":memory:", check_same_thread=False)
db.executescript("""CREATE TABLE djmdPlaylist (ID, Name, ParentID, Attribute, rb_local_deleted, Seq);
CREATE TABLE djmdSongPlaylist (PlaylistID, ContentID, TrackNo, rb_local_deleted);
CREATE TABLE djmdContent (ID, FolderPath);
INSERT INTO djmdPlaylist VALUES ('1','BrainOrder','root',1,0,1),('10','Boda Ana 2025','1',0,0,1),('20','Otra mía','1',0,0,2),('30','Fuera','root',0,0,3);
INSERT INTO djmdContent VALUES ('a','/m/a.mp3');
INSERT INTO djmdSongPlaylist VALUES ('10','a',1,0);""")


class NoClose:
    def __getattr__(self, k):
        return getattr(db, k)

    def close(self):
        pass


RS.connect_ro = lambda path=None: NoClose()
got = DJ.rekordbox({"rekordbox_folder": "BrainOrder", "folder_playlists": [{"program": "rekordbox", "ref": "10", "name": "Boda Ana 2025"}]})
assert set(got) == {"10", "30"}, got  # la 20 es de BrainOrder (dentro de su carpeta): no cuenta como tuya
assert got["10"]["paths"] == [os.path.normpath("/m/a.mp3")] or got["10"]["paths"] == ["/m/a.mp3"]
print("lectura ok")

# ---------------- después de agregar: mover ya, o pendiente si Rekordbox está abierto, o no quitar si faltan canciones
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "_rb_adopt_after_import")][0]
o = A.__new__(A)
o._cfg = {"rekordbox_folder": "BrainOrder"}
o._analysis = lambda: [{"id": "sp1", "name": "Boda Ana 2025"}]
o._build_analysis = lambda light=True: None
o._progress = lambda *a, **k: None
o._update_sp = lambda f: None
ST["pls"] = [folder, pl("50", "Nueva", "root", "a")]
RUNNING[0] = True
res = o._rb_adopt_after_import("rekordbox", "50", {"pid": "sp1", "result": {"name": "Boda Ana 2025"}}, {})
assert res == {"state": "pending", "mode": "move"} and o._cfg["rb_adopt"], res
RUNNING[0] = False
out = o._rb_adopt_run()  # cerraste Rekordbox
assert out["moved"] == 1 and o._cfg["rb_adopt"] == [] and ST["pls"][1].ParentID == "1" and ST["pls"][1].Name == "Boda Ana 2025"
assert "10" not in rb_cambios.load_baseline() and "50" in rb_cambios.load_baseline()
# sumada a una de Spotify pero con canciones que Spotify no encontró: la original se queda
res = o._rb_adopt_after_import("rekordbox", "51", {"pid": "sp9", "result": {"merged_into": "Salsa", "spotify": {"state": "ok", "unresolved": ["x"]}}}, {})
assert res["state"] == "kept" and not o._cfg["rb_adopt"], res
# la opción apagada: no se toca nada
assert o._rb_adopt_after_import("rekordbox", "52", {"pid": "p", "result": {"name": "x"}}, {"adopt": False}) is None
# otros programas: no aplica
assert o._rb_adopt_after_import("traktor", "52", {"pid": "p", "result": {"name": "x"}}, {}) is None
shutil.rmtree(TMP)
print("OK")
