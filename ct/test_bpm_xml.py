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

# --- la API de la app (elegir XML guardado en cfg + armar)
import app  # noqa: E402
import config  # noqa: E402

config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "bpm_xml_build")][0]
o = A.__new__(A)
o._cfg = {}
o._task = lambda fn, k, l, files=False: {"ok": True, **fn()}
o._progress = lambda *a, **k: None
assert o.bpm_xml_state()["export"] is None

try:
    o._task = lambda fn, k, l, files=False: fn()
    o.bpm_xml_build([{"id": "11", "path": a, "f": 0.5}])
    raise AssertionError("sin XML elegido debía fallar")
except RuntimeError:
    pass
o._task = lambda fn, k, l, files=False: {"ok": True, **fn()}
o._cfg["rb_xml_export"] = str(exp)
st = o.bpm_xml_state()["export"]
assert st["exists"] and st["age_h"] < 1, st
r = o.bpm_xml_build([{"id": "11", "path": a, "f": 0.5}, {"id": "12", "path": b_, "f": 2}, {"id": "x", "path": c, "f": 3}])
assert r["ok"] and r["done"] == 2 and r["out"].endswith(B.OUT_NAME) and o._cfg["bpm_xml_last"]["done"] == 2, r
print("ok api bpm_xml")
