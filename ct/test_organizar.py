"""2.51.0: las playlists sin grupo van a «Organizar» (Rekordbox, disco y tus otros programas de DJ) y lo que
tiene el mismo nombre en el destino va a _duplicados en vez de quedar saltado."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP / "sup"
config.SUPPORT_DIR.mkdir()
config.save = lambda c: None
import app  # noqa: E402
import grupos as G  # noqa: E402
from destinos import engine as EN, m3u as M3, serato as SE, traktor as TK  # noqa: E402

# ------------------------------------------------ cálculo
t = G.effective_tree({}, {"a": "Techno"}, {}, True, True, "Organizar", ["a", "b", "c"])
assert t == {"a": ["Techno"], "b": ["Organizar"], "c": ["Organizar"]}, t
assert G.effective_tree({}, {"a": "Techno"}, {}, False, True, "Organizar", ["b"]) == {}
# Rekordbox: suelta en la carpeta principal -> pendiente a «Organizar»; dentro de «Organizar» -> sin grupo
g, pend, ch = G.follow_rekordbox({"a": "Techno", "c": "House"}, {"b": ["Organizar"], "c": ["Organizar"]},
                                 {"a", "b", "c", "d"}, {}, "Organizar")
assert g == {} and pend == {"a": ["Organizar"], "d": ["Organizar"]} and sorted(ch) == ["a", "c"], (g, pend, ch)
print("cálculo ok")

# ------------------------------------------------ Traktor
nml = TMP / "collection.nml"
nml.write_text('<?xml version="1.0" encoding="UTF-8" standalone="no" ?><NML VERSION="19"><COLLECTION ENTRIES="0"></COLLECTION>'
               '<PLAYLISTS><NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="1"><NODE TYPE="FOLDER" NAME="BrainOrder">'
               '<SUBNODES COUNT="2"><NODE TYPE="PLAYLIST" NAME="Acid"><PLAYLIST ENTRIES="0" TYPE="LIST" UUID="x"></PLAYLIST></NODE>'
               '<NODE TYPE="FOLDER" NAME="Viejo"><SUBNODES COUNT="1"><NODE TYPE="PLAYLIST" NAME="Salsa"><PLAYLIST ENTRIES="0" TYPE="LIST" UUID="y"></PLAYLIST></NODE></SUBNODES></NODE>'
               '</SUBNODES></NODE></SUBNODES></NODE></PLAYLISTS></NML>', "utf-8")
TK.running = lambda: False
TK.nml_path = lambda cfg: str(nml)
an = [{"id": "a", "name": "Acid", "tracks": []}, {"id": "s", "name": "Salsa", "tracks": []}]
TK.sync(an, {"rekordbox_folder": "BrainOrder", "_trails": {"a": ["Techno"], "s": ["Organizar"]}})
col = TK.Collection(nml)
names = lambda sub, pre="": sum([[pre + n.get("NAME")] + (names(n.find("SUBNODES"), pre + n.get("NAME") + "/")
                                  if n.find("SUBNODES") is not None else []) for n in sub.findall("NODE")], [])
got = names(col.folder_sub(["BrainOrder"]))
assert got == ["Techno", "Techno/Acid", "Organizar", "Organizar/Salsa"], got  # «Viejo» quedó vacía y se quitó
TK.edit({"rekordbox_folder": "BrainOrder"}, {"Acid": "Acid 2"}, ["Salsa"])
assert names(TK.Collection(nml).folder_sub(["BrainOrder"])) == ["Techno", "Techno/Acid 2", "Organizar"]
print("Traktor ok")

# ------------------------------------------------ M3U
out = TMP / "m3u"
(out / "BrainOrder").mkdir(parents=True)
(out / "BrainOrder" / "Acid.m3u8").write_text("#EXTM3U\n")
cfgm = {"rekordbox_folder": "BrainOrder", "destinations": {"m3u": {"enabled": True, "folder": str(out)}},
        "_trails": {"a": ["Techno"], "s": ["Organizar"]}}
M3.sync(an, cfgm)
assert sorted(str(p.relative_to(out)) for p in out.rglob("*.m3u8")) == ["BrainOrder/Organizar/Salsa.m3u8", "BrainOrder/Techno/Acid.m3u8"]
M3.edit(cfgm, {"Acid": "Acid 2"}, [])
assert (out / "BrainOrder" / "Techno" / "Acid 2.m3u8").exists()
print("M3U ok")

# ------------------------------------------------ Serato
sd = TMP / "_Serato_"
(sd / "Subcrates").mkdir(parents=True)
(sd / "Subcrates" / "BrainOrder.crate").write_bytes(SE.build_crate([]))
(sd / "Subcrates" / "BrainOrder%%Viejo.crate").write_bytes(SE.build_crate([]))
(sd / "Subcrates" / "BrainOrder%%Viejo%%Acid.crate").write_bytes(SE.build_crate(["m/x.mp3"]))
SE.running = lambda: False
cfgs = {"rekordbox_folder": "BrainOrder", "destinations": {"serato": {"enabled": True, "dir": str(sd)}},
        "_trails": {"a": ["Techno"], "s": ["Organizar"]}}
x = TMP / "x.mp3"
x.write_bytes(b"x")
SE.sync([{"id": "a", "name": "Acid", "tracks": [{"status": "ok", "source": str(x), "name": "x"}]},
         {"id": "s", "name": "Salsa", "tracks": [{"status": "ok", "source": str(x), "name": "x"}]}], cfgs)
crates = sorted(f.stem for f in (sd / "Subcrates").glob("*.crate"))
assert crates == ["BrainOrder", "BrainOrder%%Organizar", "BrainOrder%%Organizar%%Salsa", "BrainOrder%%Techno",
                  "BrainOrder%%Techno%%Acid"], crates  # «Viejo» se fue con la que estaba adentro
SE.edit(cfgs, {"Acid": "Acid 2"}, ["Salsa"])
crates = sorted(f.stem for f in (sd / "Subcrates").glob("*.crate"))
assert "BrainOrder%%Techno%%Acid 2" in crates and "BrainOrder%%Organizar%%Salsa" not in crates, crates
print("Serato ok")

# ------------------------------------------------ Engine DJ (lo justo de su base)
db = TMP / "m.db"
c = sqlite3.connect(db)
c.executescript("""CREATE TABLE Information (uuid TEXT); INSERT INTO Information VALUES ('u');
CREATE TABLE Track (id INTEGER PRIMARY KEY, path TEXT, filename TEXT, title TEXT);
CREATE TABLE Playlist (id INTEGER PRIMARY KEY, title TEXT, parentListId INTEGER, nextListId INTEGER, isPersisted INTEGER, lastEditTime INTEGER, isExplicitlyExported INTEGER);
CREATE TABLE PlaylistEntity (id INTEGER PRIMARY KEY, listId INTEGER, trackId INTEGER, databaseUuid TEXT, nextEntityId INTEGER, membershipReference INTEGER);
INSERT INTO Playlist (id, title, parentListId, nextListId) VALUES (1,'BrainOrder',0,0),(2,'Viejo',1,0),(3,'Acid',2,0);""")
c.commit()
c.close()
EN.db_path = lambda cfg: db
EN.library_dir = lambda cfg: TMP
EN.running = lambda: False
EN.sync([{"id": "a", "name": "Acid", "tracks": []}], {"rekordbox_folder": "BrainOrder", "_trails": {"a": ["Techno"]}})
c = sqlite3.connect(db)
rows = {r[0]: (r[1], r[2]) for r in c.execute("SELECT id, title, parentListId FROM Playlist")}
by = {t: p for t, p in rows.values()}
assert "Viejo" not in by and by["Techno"] == 1 and rows[[i for i, (t, p) in rows.items() if t == "Acid"][0]][1] != 1, rows
assert [t for t, p in rows.values()].count("Acid") == 1
c.close()
print("Engine DJ ok")

# ------------------------------------------------ disco: mismo nombre en el destino -> _duplicados
BL = TMP / "BL"
(BL / "Techno" / "Acid").mkdir(parents=True)
(BL / "Acid").mkdir(parents=True)
(BL / "Techno" / "Acid" / "uno.mp3").write_bytes(b"queda")
(BL / "Acid" / "uno.mp3").write_bytes(b"llega")
(BL / "Acid" / "dos.mp3").write_bytes(b"dos")
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "_dups_out")][0]
o = A.__new__(A)
o._cfg = {"dest_root": str(BL)}
o._progress = lambda *a, **k: None
FIX = []
o._dj_fix = lambda moved, repoint=None: FIX.append((moved, repoint)) or ({}, [])
app.destinos.DESTINATIONS["rekordbox"].available = lambda cfg: False
ops = [(str(BL / "Acid" / "uno.mp3"), str(BL / "Techno" / "Acid")), (str(BL / "Acid" / "dos.mp3"), str(BL / "Techno" / "Acid"))]
keep, ch, dup_of = o._dups_out(ops)
assert keep == [ops[1]] and dup_of == {ops[0][0]: str(BL / "Techno" / "Acid" / "uno.mp3")}, (keep, dup_of)
assert ch[ops[0][0]] == str(BL / "_duplicados" / "Acid" / "uno.mp3") and Path(ch[ops[0][0]]).read_bytes() == b"llega"
assert (BL / "Techno" / "Acid" / "uno.mp3").read_bytes() == b"queda" and FIX == [({}, dup_of)]
print("repetidas ok")
print("OK")
