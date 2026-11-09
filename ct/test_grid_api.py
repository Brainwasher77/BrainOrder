"""grid_scan / grid_audio / grid_ok de punta a punta con una colección falsa de Rekordbox (sqlite + ANLZ)."""
import os
import shutil
import sqlite3
import sys
import tempfile
import wave
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import app  # noqa: E402
import armonia  # noqa: E402
import config  # noqa: E402
import grillas  # noqa: E402
import test_grillas as T  # noqa: E402

config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "grid_scan")][0]
root = Path(tempfile.mkdtemp())
share = root / "share"
music = root / "music"
music.mkdir()


def song(cid, name, bpm_audio, grid, genre="", cues=()):
    """Escribe el audio (si bpm_audio) y su ANLZ; devuelve la fila para djmdContent."""
    p = music / name
    if bpm_audio:
        a = T.make_audio(bpm_audio, 1000, 170000)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(grillas.SR)
            w.writeframes(a.tobytes())
    else:
        p.write_bytes(b"x")
    rel = f"/PIONEER/USBANLZ/{cid}/ANLZ0000.DAT"
    if grid is not None:
        (share / rel.strip("/")).parent.mkdir(parents=True, exist_ok=True)
        (share / rel.strip("/")).write_bytes(T.anlz(grid))
    return (cid, str(p), name, genre, rel if grid is not None else None, list(cues))


g_ok = T.make_grid(124, 1000, 170000)
rows = [
    song("1", "bien.wav", 124, g_ok, "House"),
    song("2", "corrida.wav", 124, T.make_grid(124, 960, 170000), "House"),
    song("3", "doble.wav", None, T.make_grid(190, 100, 60000), "Reggaeton"),
    song("4", "sin grilla.wav", None, None),
    song("5", "cues.wav", None, g_ok, "", [g_ok[8][2] + 30, g_ok[40][2] + 31]),
]
rows.append(("6", str(music / "no existe.wav"), "perdida", "", None, []))
db = root / "master.db"
con = sqlite3.connect(db)
con.executescript("""
CREATE TABLE djmdContent (ID, FolderPath, Title, ArtistID, GenreID, Length, AnalysisDataPath, BPM, rb_local_deleted);
CREATE TABLE djmdArtist (ID, Name); CREATE TABLE djmdGenre (ID, Name);
CREATE TABLE djmdCue (ContentID, InMsec, rb_local_deleted);
CREATE TABLE djmdPlaylist (ID, Name, Attribute, rb_local_deleted); CREATE TABLE djmdSongPlaylist (ContentID, PlaylistID, rb_local_deleted);
INSERT INTO djmdArtist VALUES (1, 'Brainwasher');
""")
for i, (cid, path, title, genre, rel, cues) in enumerate(rows):
    if genre:
        con.execute("INSERT INTO djmdGenre VALUES (?, ?)", (i, genre))
    con.execute("INSERT INTO djmdContent VALUES (?,?,?,?,?,?,?,?,0)",
                (cid, path, title, 1, i if genre else None, 170, rel, 12400))
    for c in cues:
        con.execute("INSERT INTO djmdCue VALUES (?,?,0)", (cid, c))
con.commit()

o = A.__new__(A)
o._cfg = {}
o._task = lambda fn, k, l, files=False: {"ok": True, **fn()}
o._progress = lambda *a, **k: None
o._GRID_FILE = root / "grillas.json"
o._rb_read = lambda fn, tag="": fn(sqlite3.connect(db))
app.rekordbox_sync.RB_DIR = root
app.rekordbox_sync.rekordbox_running = lambda: False
armonia.info = lambda p: {"bpm": None}

r = o.grid_scan()
got = {x["title"]: sorted(w["c"] for w in x["why"]) for x in r["items"]}
print("rápida:", got)
assert got == {"doble.wav": ["double"], "sin grilla.wav": ["nogrid"], "cues.wav": ["cues"]}, got
assert r["total"] == 5  # la perdida no cuenta

# medir el audio (decodificador falso que lee el wav tal cual)
grillas.decoder = lambda: ("fake", "")


def fake_decode(path, dec, timeout=180):
    import array
    try:
        with wave.open(path, "rb") as w:
            a = array.array("h")
            a.frombytes(w.readframes(w.getnframes()))
        return a
    except Exception:
        return None  # como el real: audio que no se puede leer


grillas.decode = fake_decode
r = o.grid_audio(["1", "2", "3"])
got = {x["title"]: sorted(w["c"] for w in x["why"]) for x in r["items"]}
print("con audio:", got, "medidas:", r["measured"])
assert got["corrida.wav"] == ["shift"], got
assert "bien.wav" not in got
assert r["measured"] == 3 and r["just_measured"] == 3
assert next(x for x in r["items"] if x["title"] == "doble.wav")["audio"] == "err"  # audio ilegible: se avisa
# la caché se reutiliza: medir otra vez no vuelve a medir
assert o.grid_audio(["1", "2"])["just_measured"] == 0

# «Está bien» oculta mientras la grilla no cambie
it = next(x for x in r["items"] if x["title"] == "corrida.wav")
o.grid_ok([{"id": it["id"], "sig": it["sig"]}])
r = o.grid_scan()
assert "corrida.wav" not in {x["title"] for x in r["items"]} and r["hidden"] == 1
# la corriges en Rekordbox (cambia la grilla) -> vuelve a revisarse (y la medición vieja ya no vale)
(share / "PIONEER/USBANLZ/2/ANLZ0000.DAT").write_bytes(T.anlz(T.make_grid(124, 1000, 170000)))
r = o.grid_scan()
assert r["hidden"] == 0 and "corrida.wav" not in {x["title"] for x in r["items"]}
r = o.grid_audio(["2"])
assert "corrida.wav" not in {x["title"] for x in r["items"]}, r["items"]
shutil.rmtree(root)
print("OK")
