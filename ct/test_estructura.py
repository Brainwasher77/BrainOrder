"""2.31.0: subcarpetas de Rekordbox -> carpetas en el disco, carpeta de playlists renombrada, sin repetidas."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
SUP = TMP / "support"
SUP.mkdir()
config.SUPPORT_DIR = SUP
config.save = lambda c: None
import estructura  # noqa: E402
estructura.SUPPORT_DIR = SUP
import app  # noqa: E402
import carpetas_nuevas as CN  # noqa: E402
import dj_playlists as DJ  # noqa: E402
import rb_arbol  # noqa: E402
import rb_cambios  # noqa: E402
import rekordbox_sync as RS  # noqa: E402
from fuentes import carpetas as FC  # noqa: E402

rb_cambios.BASELINE = SUP / "rb_baseline.json"
CN.STATE = SUP / "carpetas.json"

# ------------------------------------------------ árbol: carpeta renombrada y playlists en subcarpetas
rows = [("1", "BRAIN LIBRARY", "root", 1), ("2", "Techno", "1", 1), ("3", "Hard", "2", 1),
        ("10", "Acid", "2", 0), ("11", "Hard Techno", "3", 0), ("12", "Salsa", "1", 0),
        ("20", "Mías", "root", 1), ("21", "Fiesta", "20", 0), ("30", "Suelta", "root", 0)]
rid, name, ren = rb_arbol.locate(rows, ["BrainOrder"], ["10", "11", "12"])
assert (rid, name, ren) == ("1", "BRAIN LIBRARY", True), (rid, name, ren)
pls = rb_arbol.playlists(rows, "1")
assert pls == {"10": {"name": "Acid", "folder": ["Techno"]}, "11": {"name": "Hard Techno", "folder": ["Techno", "Hard"]},
               "12": {"name": "Salsa", "folder": []}}, pls
assert rb_arbol.locate(rows, ["BrainOrder"], ["99"])[0] is None  # sin pistas: no se adivina
print("árbol ok")

# ------------------------------------------------ lectura de Rekordbox (sqlite) con subcarpetas
db = sqlite3.connect(":memory:", check_same_thread=False)
db.executescript("""CREATE TABLE djmdPlaylist (ID, Name, ParentID, Attribute, rb_local_deleted, Seq);
CREATE TABLE djmdSongPlaylist (PlaylistID, ContentID, TrackNo, rb_local_deleted);
CREATE TABLE djmdContent (ID, FolderPath);""")
db.executemany("INSERT INTO djmdPlaylist VALUES (?,?,?,?,0,1)", rows)
db.executemany("INSERT INTO djmdContent VALUES (?,?)", [("a", "/m/a.mp3"), ("b", "/m/b.mp3")])
db.executemany("INSERT INTO djmdSongPlaylist VALUES (?,?,?,0)", [("11", "a", 1), ("11", "b", 2), ("21", "a", 1)])


class NoClose:
    def __getattr__(self, k):
        return getattr(db, k)

    def close(self):
        pass


RS.connect_ro = lambda path=None: NoClose()
rb_cambios.save_baseline({"10": {"pid": "spA", "name": "Acid", "paths": []},
                          "11": {"pid": "spH", "name": "Hard Techno", "paths": ["/m/a.mp3", "/m/b.mp3"]},
                          "12": {"pid": "spS", "name": "Salsa", "paths": []}})
cfg = {"rekordbox_folder": "BrainOrder"}
st = rb_cambios._read_direct(cfg, None)
assert set(st) == {"10", "11", "12"} and st["11"]["folder"] == ["Techno", "Hard"], st
assert rb_cambios.FOUND == {"name": "BRAIN LIBRARY", "renamed": True}, rb_cambios.FOUND
# nada aparece como borrado ni creado: solo el nombre de la carpeta
assert [c["type"] for c in rb_cambios.diff(rb_cambios.load_baseline(), st)] == []
# y en «Playlists nuevas» no salen las de BrainOrder aunque la carpeta tenga otro nombre
got = DJ.rekordbox(cfg)
assert set(got) == {"21", "30"}, got
tr = estructura.trails(st, rb_cambios.load_baseline(), [])
assert tr == {"spA": ["Techno"], "spH": ["Techno", "Hard"]}, tr
print("lectura ok")

# ------------------------------------------------ sincronizar: la que moviste a una subcarpeta no se repite


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


ST = {}


class FakeDB:
    def __init__(self, *a, **k):
        self.pls = ST["pls"]
        self.n = 100

    def get_playlist(self, ID=None, ParentID=None, Name=None):
        if ID is not None:
            return next((p for p in self.pls if str(p.ID) == str(ID)), None)
        if ParentID is None and Name is None:
            return Q(self.pls)
        return Q([p for p in self.pls if p.ParentID == ParentID and p.Name == Name])

    def create_playlist_folder(self, name):
        p = PL("F", name, "root", 1)
        self.pls.append(p)
        return p

    def create_playlist(self, name, parent=None):
        self.n += 1
        p = PL(str(self.n), name, parent.ID)
        self.pls.append(p)
        return p

    def get_artist(self, Name=None):
        return Q([])

    def add_artist(self, name):
        return type("A", (), {"ID": 1})()

    def add_content(self, path, **k):
        return Content(path, path)

    def add_to_playlist(self, pl, c):
        pl.Songs.append(Song(c, len(pl.Songs) + 1))

    def remove_from_playlist(self, pl, s):
        pl.Songs.remove(s)

    def delete_playlist(self, pl):
        self.pls.remove(pl)

    def rename_playlist(self, pl, name):
        pl.Name = name

    def query(self, *a):
        raise RuntimeError

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


import pyrekordbox  # noqa: E402
pyrekordbox.MasterDatabase = FakeDB
RS.backup = lambda: Path("/tmp/x.db")
RS.rekordbox_running = lambda: False
RS.content_by_path = lambda db, p: next((s.Content for x in ST["pls"] for s in x.Songs if s.Content.FolderPath == p),
                                        None) or Content(p, p)
ca, cb, cc = Content("a", "/m/a.mp3"), Content("b", "/m/b.mp3"), Content("c", "/m/c.mp3")
root, tech = PL("1", "BRAIN LIBRARY", "root", 1), PL("2", "Techno", "1", 1)
hard = PL("11", "Hard Techno", "2")
hard.Songs = [Song(cb, 1), Song(ca, 2)]          # tu orden en Rekordbox
twin = PL("40", "Hard Techno", "1")              # la repetida que creó un Organizar de antes
twin.Songs = [Song(ca, 1), Song(cc, 2)]
ST["pls"] = [root, tech, hard, twin]
analysis = [{"id": "spH", "name": "Hard Techno", "tracks": [
    {"status": "ok", "source": "/m/a.mp3", "name": "a", "artists": []},
    {"status": "ok", "source": "/m/b.mp3", "name": "b", "artists": []}]}]
st = RS.sync(analysis, {"rekordbox_folder": "BrainOrder", "rb_master": True,
                        "_rb_base": {"11": {"pid": "spH", "paths": ["/m/a.mp3", "/m/b.mp3"]},
                                     "40": {"pid": "spH", "paths": ["/m/a.mp3", "/m/c.mp3"]}}})
assert [p.ID for p in ST["pls"]] == ["1", "2", "11"], [(p.ID, p.Name, p.ParentID) for p in ST["pls"]]
assert hard.ParentID == "2" and [s.ContentID for s in hard.Songs] == ["b", "a", "c"], [s.ContentID for s in hard.Songs]
assert st["twins_removed"] == 1 and st["playlists_created"] == 0 and "11" in st["baseline"], st
print("sync ok")

# una playlist TUYA en una subcarpeta que se llama igual que una de BrainOrder (MGNO/Pop latino vs tu «Pop latino»
# de Spotify): no se casan por nombre, no se suman y la de BrainOrder queda aparte
mg = PL("50", "Pop latino", "2")
mg.Songs = [Song(ca, 1)]
ST["pls"] = [root, tech, hard, mg]
st = RS.sync([{"id": "spP", "name": "Pop latino", "tracks": [{"status": "ok", "source": "/m/b.mp3", "name": "b", "artists": []}]}],
             {"rekordbox_folder": "BrainOrder", "rb_master": True, "_rb_base": {}})
assert [s.ContentID for s in mg.Songs] == ["a"], [s.ContentID for s in mg.Songs]
loose = [p for p in ST["pls"] if p.Name == "Pop latino" and p.ParentID == "1"]
assert len(loose) == 1 and [s.ContentID for s in loose[0].Songs] == ["b"]
assert not estructura.trails({"50": {"name": "Pop latino", "folder": ["Techno"]}}, {}, [{"id": "spP", "name": "Pop latino"}])
print("mismo nombre en subcarpeta ok")

# ------------------------------------------------ disco: carpetas como Rekordbox
music = TMP / "Music"
old_root, new_root = music / "Spotify playlists", music / "BRAIN LIBRARY"
for n in ("Hard Techno", "Acid", "Salsa", "Cumbia"):
    (old_root / n).mkdir(parents=True)
    (old_root / n / f"{n} - uno.mp3").write_bytes(b"x")
(old_root / "Mi carpeta").mkdir()
(old_root / "Mi carpeta" / "x.mp3").write_bytes(b"x")
os.rename(old_root, new_root)  # le cambiaste el nombre en Finder

A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "_root_migrate")][0]
o = A.__new__(A)
o._cfg = {"dest_root": str(old_root), "inbox": str(music / "Nuevas"), "rekordbox_folder": "BrainOrder",
          "folder_playlists": [{"name": "Mi carpeta", "path": str(old_root / "Mi carpeta")}],
          "pl_groups": {FC.pid_for(old_root / "Mi carpeta"): "Varios"}, "rb_mirror": True}
an = [{"id": i, "name": n, "folder": str(old_root / n), "tracks": []}
      for i, n in (("spH", "Hard Techno"), ("spA", "Acid"), ("spS", "Salsa"), ("spC", "Cumbia"))]
(SUP / "analysis_cache.json").write_text(json.dumps(an))
app.CACHE_ANALYSIS = SUP / "analysis_cache.json"
(SUP / "durations.json").write_text(json.dumps({str(old_root / "Acid" / "Acid - uno.mp3"): 300}))
o._an = None
o._files = app.threading.Lock()
o._state = app.threading.RLock()
o._progress = lambda *a, **k: None
r = o._root_check()
assert r and r["new"] == str(new_root), r
assert o._cfg["dest_root"] == str(new_root)
new_pid = FC.pid_for(new_root / "Mi carpeta")
assert o._cfg["folder_playlists"][0]["path"] == str(new_root / "Mi carpeta") and new_pid in o._cfg["pl_groups"], o._cfg
assert str(new_root) in (SUP / "analysis_cache.json").read_text() and "Spotify playlists" not in (SUP / "durations.json").read_text()
assert o._cfg["root_repoint"] == [[str(old_root), str(new_root)]]
fm = estructura.file_map(old_root, new_root)
assert fm[str(old_root / "Acid" / "Acid - uno.mp3")] == str(new_root / "Acid" / "Acid - uno.mp3")
assert o._root_check() is None  # una sola vez
print("carpeta renombrada ok")

# ya lo habías cambiado en Ajustes antes de esta versión: lo guardado apunta a la vieja y se corrige igual
o2 = A.__new__(A)
o2._cfg = {"dest_root": str(new_root), "folder_playlists": []}
an_old = [{"id": i, "name": n, "folder": str(old_root / n)} for i, n in (("1", "Hard Techno"), ("2", "Acid"), ("3", "Salsa"))]
(SUP / "analysis_cache.json").write_text(json.dumps(an_old))
o2._an = None
r2 = o2._root_check()
assert r2 and r2["old"] == str(old_root) and str(new_root / "Acid") in (SUP / "analysis_cache.json").read_text(), r2
print("rutas viejas tras Ajustes ok")

# ------------------------------------------------ mudar a subcarpetas como en Rekordbox
moved_log = []


def fake_relocate(ops, cfg, progress=None):
    ch = {}
    for src, dest in ops:
        d = Path(dest) / Path(src).name
        if d.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, d)
        ch[src] = str(d)
    moved_log.append(ch)
    return {"moved": len(ch), "skipped": [], "changes": ch}


app.organizador.relocate = fake_relocate
app.historial.record = lambda *a, **k: "op1"
o._dj_fix = lambda changes, repoint=None: ({}, [])
o._dj_precheck = lambda keys=None: None
o._cfg["rb_tree"] = {"spH": ["Techno", "Hard"], "spA": ["Techno"], new_pid: ["Varios"]}
loaded = o._mirror_folders([{"id": "spH", "name": "Hard Techno"}, {"id": "spA", "name": "Acid"},
                            {"id": "spS", "name": "Salsa"}])
an2 = [{**p, "tracks": []} for p in loaded] + [{"id": new_pid, "name": "Mi carpeta", "folder": str(new_root / "Mi carpeta"),
                                                "tracks": []}]
assert loaded[0]["folder"] == str(new_root / "Techno" / "Hard" / "Hard Techno"), loaded[0]
assert "folder" not in loaded[2]
assert o._mirror_stale([{"id": "spH", "name": "Hard Techno", "folder": str(new_root / "Hard Techno")}])
res = o._mirror_apply(an2)
assert res["playlists"] == 3 and res["moved"] == 3, res
assert (new_root / "Techno" / "Hard" / "Hard Techno" / "Hard Techno - uno.mp3").exists()
assert (new_root / "Techno" / "Acid" / "Acid - uno.mp3").exists()
assert (new_root / "Salsa" / "Salsa - uno.mp3").exists()  # suelta en Rekordbox: se queda donde estaba
assert not (new_root / "Hard Techno").exists() and not (new_root / "Acid").exists()
mine = new_root / "Varios" / "Mi carpeta"
assert (mine / "x.mp3").exists() and o._cfg["folder_playlists"][0]["path"] == str(mine)
assert FC.pid_for(mine) in o._cfg["pl_groups"] and o._cfg["pl_dirs"]["spH"].endswith("Hard Techno")
print("mudanza ok")

# la mueves de subcarpeta en Rekordbox: se vuelve a mudar desde donde quedó
o._cfg["rb_tree"]["spH"] = ["Techno"]
an3 = [{**p, "tracks": []} for p in o._mirror_folders([{"id": "spH", "name": "Hard Techno"}])]
res = o._mirror_apply(an3)
assert res and (new_root / "Techno" / "Hard Techno" / "Hard Techno - uno.mp3").exists(), res
assert not (new_root / "Techno" / "Hard").exists()
print("cambio de subcarpeta ok")

# ------------------------------------------------ las subcarpetas no son una «playlist grande»
FC.OTHER_DIRS = {FC._nk(new_root / "Techno" / "Hard Techno"), FC._nk(new_root / "Techno" / "Acid")}
(new_root / "Techno" / "suelta.mp3").write_bytes(b"x")
files = FC.audio_files(new_root / "Techno")
assert [Path(f).name for f in files] == ["suelta.mp3"], files
grp = new_root / "Latino" / "Bachata nueva"
grp.mkdir(parents=True)
(grp / "b.mp3").write_bytes(b"x")
an_now = [{"id": "spH", "folder": str(new_root / "Techno" / "Hard Techno")}, {"id": "spA", "folder": str(new_root / "Techno" / "Acid")},
          {"id": "spS", "folder": str(new_root / "Salsa")}]
o._cfg["library_roots"] = []
un = {x["name"] for x in CN.unmatched(o._cfg, an_now)}
assert "Latino" not in un and "Bachata nueva" in un and "Techno" not in un and "Cumbia" in un, un
print("subcarpetas ok")
print("OK")
