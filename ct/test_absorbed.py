"""2.33.0: detectar playlists que se tragaron una carpeta de Rekordbox (Crossover, Brainwasher)."""
import os
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
import rb_cambios  # noqa: E402
import rekordbox_sync as RS  # noqa: E402

rb_cambios.BASELINE = TMP / "b.json"
db = sqlite3.connect(":memory:", check_same_thread=False)
db.executescript("""CREATE TABLE djmdPlaylist (ID, Name, ParentID, Attribute, rb_local_deleted, Seq);
CREATE TABLE djmdSongPlaylist (PlaylistID, ContentID, TrackNo, rb_local_deleted);
CREATE TABLE djmdContent (ID, FolderPath);""")
pl = [("1", "BRAINLIBRARY", "root", 1), ("2", "Crossover", "1", 0), ("3", "Techno", "1", 0),
      ("10", "Crossover", "root", 1), ("11", "MGNO", "10", 1), ("12", "ADC", "10", 1),
      ("13", "Salsa", "11", 0), ("14", "Pop", "11", 0), ("15", "Rumba ADC", "12", 0),
      ("20", "Eventos", "root", 1), ("21", "Boda", "20", 0), ("22", "Grado", "20", 0)]
db.executemany("INSERT INTO djmdPlaylist VALUES (?,?,?,?,0,1)", pl)
songs = {"13": "abc", "14": "de", "15": "fg", "2": "abcdefx", "3": "t", "21": "a", "22": "b"}
for pid, ks in songs.items():
    for n, k in enumerate(ks):
        db.execute("INSERT INTO djmdSongPlaylist VALUES (?,?,?,0)", (pid, k, n))
db.executemany("INSERT INTO djmdContent VALUES (?,?)", [(k, f"/m/{k}.mp3") for k in "abcdefgxt"])


class NoClose:
    def __getattr__(self, k):
        return getattr(db, k)

    def close(self):
        pass


RS.connect_ro = lambda path=None: NoClose()
rb_cambios.save_baseline({"2": {"pid": "spX", "name": "Crossover", "paths": []}})
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "absorbed_scan")][0]
o = A.__new__(A)
o._cfg = {"rekordbox_folder": "BRAINLIBRARY"}
o._an = [{"id": "spX", "name": "Crossover"}]
r = o.absorbed_scan()
assert r["ok"] and len(r["items"]) == 1, r
x = r["items"][0]
assert (x["folder_id"], x["global_rid"], x["pid"], x["playlists"], x["common"]) == ("10", "2", "spX", 3, 6), x
assert x["subs"] == ["ADC", "MGNO"]
print("OK")
