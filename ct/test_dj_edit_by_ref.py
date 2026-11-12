"""Lo que cambias en BrainOrder llega a la playlist original en Traktor, Serato y Engine DJ (edit_by_ref)."""
import os, sys, tempfile, shutil, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from destinos import traktor as T, serato as S, engine as E
import dj_playlists as DJ

root = Path(tempfile.mkdtemp())
music = root / "m"
music.mkdir()
a, b, c = (str(music / n) for n in ("a.mp3", "b.mp3", "c.mp3"))
for f in (a, b, c):
    Path(f).write_bytes(b"x")
for m in (T, S, E):
    m.running = lambda: False

# ---- Traktor: playlist con UUID dentro de una carpeta, y otra sin UUID (su id es la ruta)
nml = root / "collection.nml"
col_xml = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<NML VERSION="19"><COLLECTION ENTRIES="0"></COLLECTION><PLAYLISTS><NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="1">
<NODE TYPE="FOLDER" NAME="Brazil"><SUBNODES COUNT="2">
<NODE TYPE="PLAYLIST" NAME="Forro"><PLAYLIST ENTRIES="0" TYPE="LIST" UUID="u1"></PLAYLIST></NODE>
<NODE TYPE="PLAYLIST" NAME="MPB"><PLAYLIST ENTRIES="0" TYPE="LIST"></PLAYLIST></NODE>
</SUBNODES></NODE></SUBNODES></NODE></PLAYLISTS></NML>"""
nml.write_text(col_xml, "utf-8")
cfg = {"destinations": {"traktor": {"nml": str(nml), "enabled": True}, "serato": {"dir": str(root / "_Serato_"), "enabled": True},
                        "engine": {"dir": str(root / "Engine Library"), "enabled": True}}}
r = T.edit_by_ref(cfg, [{"ref": "u1", "add": [{"source": a}, {"source": b}, {"source": a}]}])
assert r["added"] == 2, r
r = T.edit_by_ref(cfg, [{"ref": "u1", "remove": [a]}, {"ref": "Brazil/MPB", "add": [{"source": c}], "rename": "MPB pop"}])
assert r["removed"] == 1 and r["renamed"] == 1 and r["refs"] == {"Brazil/MPB": "Brazil/MPB pop"}, r
lists = DJ.traktor(cfg)
assert [Path(x).name for x in lists["u1"]["paths"]] == ["b.mp3"], lists
assert lists["Brazil/MPB pop"]["name"] == "MPB pop" and [Path(x).name for x in lists["Brazil/MPB pop"]["paths"]] == ["c.mp3"]
r = T.edit_by_ref(cfg, [{"ref": "Brazil/MPB pop", "delete": True}])
assert r["deleted"] == 1 and "Brazil/MPB pop" not in DJ.traktor(cfg)
print("Traktor OK")

# ---- Serato: crate «Brazil%%Forro» con un subcrate; agregar, quitar, renombrar (el subcrate va con él)
sub = root / "_Serato_" / "Subcrates"
sub.mkdir(parents=True)
rel = lambda p: S._volume_of(p)[1]
(sub / "Brazil%%Forro.crate").write_bytes(S.build_crate([rel(a)]))
(sub / "Brazil%%Forro%%Pe de serra.crate").write_bytes(S.build_crate([]))
r = S.edit_by_ref(cfg, [{"ref": "Brazil%%Forro", "add": [{"source": b}, {"source": b}], "remove": [a], "rename": "Forró"}])
assert r["added"] == 1 and r["removed"] == 1 and r["renamed"] == 1, r
assert r["refs"] == {"Brazil%%Forro": "Brazil%%Forró", "Brazil%%Forro%%Pe de serra": "Brazil%%Forró%%Pe de serra"}, r
assert S.crate_tracks((sub / "Brazil%%Forró.crate").read_bytes()) == [rel(b)]
assert (sub / "Brazil%%Forró%%Pe de serra.crate").exists() and not (sub / "Brazil%%Forro.crate").exists()
r = S.edit_by_ref(cfg, [{"ref": "Brazil%%Forró", "delete": True}])
assert r["deleted"] == 1 and not (sub / "Brazil%%Forró.crate").exists()
print("Serato OK")

# ---- Engine DJ: librería mínima
lib = root / "Engine Library"
(lib / "Database2").mkdir(parents=True)
db = sqlite3.connect(lib / "Database2" / "m.db")
db.executescript("""
CREATE TABLE Information (id INTEGER PRIMARY KEY, uuid TEXT);
INSERT INTO Information (uuid) VALUES ('u');
CREATE TABLE Track (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, filename TEXT, title TEXT, artist TEXT, album TEXT,
  length INTEGER, fileBytes INTEGER, fileType TEXT, dateAdded INTEGER);
CREATE TABLE Playlist (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, parentListId INTEGER, nextListId INTEGER,
  lastEditTime INTEGER);
CREATE TABLE PlaylistEntity (id INTEGER PRIMARY KEY AUTOINCREMENT, listId INTEGER, trackId INTEGER, databaseUuid TEXT,
  nextEntityId INTEGER);
INSERT INTO Playlist (id, title, parentListId, nextListId) VALUES (7, 'Forro', 0, 0);
""")
db.commit(); db.close()
r = E.edit_by_ref(cfg, [{"ref": "7", "add": [{"source": a, "name": "A"}, {"source": b, "name": "B"}]}])
assert r["added"] == 2, r
r = E.edit_by_ref(cfg, [{"ref": "7", "remove": [a], "rename": "Forró"}])
assert r["removed"] == 1 and r["renamed"] == 1, r
got = DJ.engine(cfg)
assert got["7"]["name"] == "Forró" and [Path(x).name for x in got["7"]["paths"]] == ["b.mp3"], got
r = E.edit_by_ref(cfg, [{"ref": "7", "delete": True}])
assert r["deleted"] == 1 and "7" not in DJ.engine(cfg)
print("Engine DJ OK")
shutil.rmtree(root)
print("OK")
