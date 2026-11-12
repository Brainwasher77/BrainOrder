"""bpm_xml: corregir BPM al doble / a la mitad armando un XML para «Importar a la colección» de Rekordbox."""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import bpm_xml as B  # noqa: E402

# --- retempo: ÷2 con el primer tiempo en el 4 (como sale muchas veces en Rekordbox)
new = B.retempo([(0.159, 180.0, 4)], 0.5, 219.5)
assert len(new) == 1, new
t, bpm, b = new[0]
assert abs(t - (0.159 + 60 / 180)) < 1e-6 and bpm == 90 and b == 1, new  # arranca en el primer «1»

# ÷2 con el primer tiempo en el 3: el «1» que sigue es el ancla, y el tiempo 3 (misma paridad) también se queda
new = B.retempo([(1.0, 160.0, 3)], 0.5, 100)
t, bpm, b = new[0]
assert abs(t - 1.0) < 1e-6 and bpm == 80 and b == 4, new  # el 3 rápido es el 4 lento antes del 1

# ÷2 con el primer tiempo en el 1
assert B.retempo([(0.5, 170.0, 1)], 0.5, 100) == [(0.5, 85.0, 1)]

# ÷2 con dos tramos (grilla variable): un TEMPO por tramo, numeración continua
per = 60 / 160
new = B.retempo([(0.0, 160.0, 1), (8 * per, 162.0, 1)], 0.5, 30)
assert len(new) == 2 and new[0] == (0.0, 80.0, 1), new
assert abs(new[1][0] - 8 * per) < 1e-6 and new[1][1] == 81.0 and new[1][2] == 1, new  # 8 rápidos = 4 lentos

# ×2 (BPM a la mitad): 1→1, 2→3, 3→1, 4→3
assert B.retempo([(0.2, 64.0, 2)], 2, 100) == [(0.2, 128.0, 3)]
assert B.retempo([(0.2, 64.0, 3)], 2, 100) == [(0.2, 128.0, 1)]

# --- rutas
assert B.location_path("file://localhost/Users/frank/Music/a%20b%C3%B1.mp3") == "/Users/frank/Music/a bñ.mp3"
assert B.location_path("file://localhost/C:/Music/x.mp3") == "C:/Music/x.mp3"
assert B.path_key("/Users/Frank/Música/A.mp3") == B.path_key("/Users/frank/Mu\u0301sica/a.mp3")
assert B.location_path(B.to_location("/Users/frank/Music/Él & yo (Remix) #1.mp3")) == "/Users/frank/Music/Él & yo (Remix) #1.mp3"

# --- build sobre un XML exportado falso
d = Path(tempfile.mkdtemp())
exp = d / "coleccion.xml"
a, b_, c, e = (f"/Users/frank/Music/{n}.mp3" for n in ("Reguetón 180", "Techno 64", "Otra", "Vals"))
exp.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <PRODUCT Name="rekordbox" Version="7.2.0" Company="AlphaTheta"/>
  <COLLECTION Entries="4">
    <TRACK TrackID="11" Name="Reguetón 180" Artist="X" AverageBpm="180.00" TotalTime="200" Tonality="Am" Comments="8A - Energy 6" Location="{B.to_location(a)}">
      <TEMPO Inizio="0.159" Bpm="180.00" Metro="4/4" Battito="4"/>
      <POSITION_MARK Name="" Type="0" Start="0.492" Num="0" Red="40" Green="226" Blue="20"/>
      <POSITION_MARK Name="" Type="0" Start="10.0" Num="-1"/>
    </TRACK>
    <TRACK TrackID="12" Name="Techno 64" Artist="Y" AverageBpm="64.00" TotalTime="300" Location="{B.to_location(b_)}">
      <TEMPO Inizio="0.050" Bpm="64.00" Metro="4/4" Battito="1"/>
    </TRACK>
    <TRACK TrackID="13" Name="Otra" AverageBpm="128.00" TotalTime="300" Location="{B.to_location(c)}">
      <TEMPO Inizio="0.050" Bpm="128.00" Metro="4/4" Battito="1"/>
    </TRACK>
    <TRACK TrackID="14" Name="Vals" AverageBpm="180.00" TotalTime="300" Location="{B.to_location(e)}">
      <TEMPO Inizio="0.050" Bpm="180.00" Metro="3/4" Battito="1"/>
    </TRACK>
  </COLLECTION>
  <PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS>
</DJ_PLAYLISTS>""", "utf-8")
out = d / B.OUT_NAME
res = B.build(str(exp), {a.upper(): 0.5, b_: 2, e: 0.5, "/Users/frank/Music/No está.mp3": 0.5}, out)
assert res["done"] == 2, res
assert res["missing"] == ["/Users/frank/Music/No está.mp3"], res
assert [s[1] for s in res["skipped"]] == ["compás distinto de 4/4"], res
root = ET.parse(out).getroot()
coll = root.find("COLLECTION")
assert coll.get("Entries") == "2" and root.find("PRODUCT").get("Name") == "rekordbox"
t1 = coll.find("TRACK[@TrackID='11']")
assert t1.get("AverageBpm") == "90.00" and t1.get("Tonality") == "Am" and t1.get("Comments") == "8A - Energy 6"
te = t1.findall("TEMPO")
assert len(te) == 1 and te[0].get("Bpm") == "90.00" and te[0].get("Battito") == "1" and te[0].get("Inizio") == "0.492", ET.tostring(t1)
assert [m.get("Start") for m in t1.findall("POSITION_MARK")] == ["0.492", "10.0"]  # cues intactos
assert list(t1)[0].tag == "TEMPO"  # TEMPO antes de las marcas
t2 = coll.find("TRACK[@TrackID='12']")
assert t2.get("AverageBpm") == "128.00" and t2.find("TEMPO").get("Bpm") == "128.00"
assert coll.find("TRACK[@TrackID='13']") is None  # las demás no van
pl = root.find("PLAYLISTS/NODE/NODE")
assert pl.get("Name") == B.PLAYLIST and [x.get("Key") for x in pl] == ["11", "12"]
print("ok test_bpm_xml")

# --- un botón: XML armado desde la colección (master.db) + preferencia de Rekordbox
tracks = [
    {"id": "171318462", "path": "/Users/frank/Music/BRAIN LIBRARY/Desembale/Andrés Cepeda - Para Amarte Mejor (Live).m4a",
     "title": "Para Amarte Mejor", "artist": "Andrés Cepeda", "album": "A", "genre": "Salsa", "bpm": 180.0, "len": 219,
     "track_no": 0, "bitrate": 256, "comment": "7B - Energy 5", "kind": "M4A File", "rating": 3, "year": 2001,
     "remixer": "", "label": "", "key": "F", "added": "2026-09-07", "color": 5, "plays": 2, "size": 7742993, "disc": 0,
     "composer": "", "mix": "", "sr": 44100,
     "grid": [(4, 180.0, 159), (1, 180.0, 492), (2, 180.0, 825)],
     "cues": [(1, 459, -1, ""), (2, 32458, -1, "Drop"), (0, 1000, -1, ""), (3, 2000, 4000, "")]},
    {"id": "2", "path": "/x/sin.mp3", "title": "", "artist": "", "album": "", "genre": "", "bpm": 170.0, "len": 10,
     "track_no": 0, "bitrate": 0, "comment": "", "kind": "", "rating": 0, "year": 0, "remixer": "", "label": "",
     "key": "", "added": "", "color": 0, "plays": 0, "size": 0, "disc": 0, "composer": "", "mix": "", "sr": 0,
     "grid": [], "cues": []},
    {"id": "3", "path": "/x/otra.mp3", "title": "o", "artist": "", "album": "", "genre": "", "bpm": 128.0, "len": 10,
     "track_no": 0, "bitrate": 0, "comment": "", "kind": "", "rating": 0, "year": 0, "remixer": "", "label": "",
     "key": "", "added": "", "color": 0, "plays": 0, "size": 0, "disc": 0, "composer": "", "mix": "", "sr": 0,
     "grid": [(1, 128.0, 10)], "cues": []}]
out2 = d / "db.xml"
r2 = B.build_from_db(tracks, {"171318462": 0.5, "2": 0.5}, out2)
assert r2["done"] == 1 and r2["skipped"] == [("/x/sin.mp3", "sin grilla")], r2
x = ET.parse(out2).getroot()
t = x.find("COLLECTION/TRACK")
assert t.get("AverageBpm") == "90.00" and t.get("Rating") == "153" and t.get("Colour") == "0x00FF00" and t.get("Tonality") == "F"
assert B.location_path(t.get("Location")) == tracks[0]["path"] and "(Live)" in t.get("Location")
te = t.findall("TEMPO")
assert len(te) == 1 and te[0].get("Inizio") == "0.492" and te[0].get("Bpm") == "90.00" and te[0].get("Battito") == "1"
pm = [(m.get("Num"), m.get("Start"), m.get("Type"), m.get("End"), m.get("Name")) for m in t.findall("POSITION_MARK")]
assert pm == [("0", "0.459", "0", None, ""), ("-1", "1.000", "0", None, ""), ("2", "2.000", "4", "4.000", ""),
              ("1", "32.458", "0", None, "Drop")], pm
assert x.find("PLAYLISTS/NODE/NODE").get("Name") == B.PLAYLIST
# grilla dinámica: un TEMPO por cambio
assert B.grid_tempos([(1, 120.0, 0), (2, 120.0, 500), (3, 121.0, 1000), (4, 121.0, 1496)]) == [(0.0, 120.0, 1), (1.0, 121.0, 3)]

# preferencia «rekordbox xml» en rekordbox3.settings
home = d / "home"
sdir = home / "Library" / "Application Support" / "Pioneer" / "rekordbox6"
sdir.mkdir(parents=True)
sf = sdir / "rekordbox3.settings"
sf.write_text('<?xml version="1.0"?>\n<PROPERTIES>\n  <VALUE name="masterDbDirectory" val="/x"/>\n'
              '  <VALUE name="bridgeImportedLibraryFile" val=""/>\n</PROPERTIES>\n', "utf-8")
files = B.settings_files(home)
assert files == [sf], files
assert B.set_xml_pref('/Users/frank/Library/Application Support/BrainOrder/BrainOrder · BPM corregido.xml & "x"', files) == [str(sf)]
txt = sf.read_text("utf-8")
assert 'val="/Users/frank/Library/Application Support/BrainOrder/BrainOrder · BPM corregido.xml &amp; &quot;x&quot;"' in txt, txt
assert 'masterDbDirectory" val="/x"' in txt and (sdir / "rekordbox3.settings.brainorder.bak").exists()
ET.fromstring(txt.encode())  # sigue siendo XML válido
sf.write_text('<PROPERTIES><VALUE name="otro" val=""/></PROPERTIES>', "utf-8")
assert B.set_xml_pref("/a.xml", files) == []  # sin el valor no se inventa nada
print("ok un botón")

# --- la API de la app
import app  # noqa: E402
import config  # noqa: E402

config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "bpm_xml_build")][0]
o = A.__new__(A)
o._cfg = {}
o._task = lambda fn, k, l, files=False: {"ok": True, **fn()}
o._progress = lambda *a, **k: None
o._rb_read = lambda fn, tag="": fn(None)
B_db = B.db_tracks
B.db_tracks = lambda con, share, ids: [t for t in tracks if t["id"] in ids]
config.SUPPORT_DIR = d
app.config.SUPPORT_DIR = d
app.rekordbox_sync.rekordbox_running = lambda: False
B.settings_files = lambda home=None: []
r = o.bpm_xml_build([{"id": "171318462", "f": 0.5}, {"id": "3", "f": 7}, {"id": "2", "f": "0.5"}])
assert r["ok"] and r["done"] == 1 and len(r["skipped"]) == 1 and r["pref"] == [] and not r["rekordbox_running"], r
assert Path(r["out"]).exists() and o._cfg["bpm_xml_last"]["done"] == 1
print("ok api bpm_xml")
