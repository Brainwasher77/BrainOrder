"""2.52.0: «Usar esta versión» cuenta aunque las Reglas dejen fuera el archivo (duración mínima) y con la ruta guardada."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import biblioteca as B  # noqa: E402

root = Path(tempfile.mkdtemp())
dest, inbox, other = root / "dest", root / "inbox", root / "otra"
for d in (dest, inbox, other):
    d.mkdir()
f = inbox / "John Carpenter - Halloween Theme (Intro Edit).mp3"
f.write_bytes(b"x")
B.duration = lambda p: 40.0  # más corto que el mínimo
pl = [{"id": "p1", "name": "Halloween Theme", "tracks": [{"id": "t1", "name": "Halloween Theme - Main Title", "artists": ["John Carpenter"]}]}]
cfg = {"dest_root": str(dest), "inbox": str(inbox), "rules": {"min_seconds": 60}}
st = lambda c: B.analyze(pl, c)[0]["tracks"][0]["status"]
assert st(cfg) == "missing"
cfg["version_links"] = {"t1": [B.norm(f.stem)]}
assert st(cfg) == "inbox", "con el nombre aceptado debe contar aunque sea corta"
# fuera de tus carpetas: cuenta por la ruta guardada
g = other / "Otra cosa.mp3"
g.write_bytes(b"x")
cfg2 = {"dest_root": str(dest), "inbox": str(inbox), "rules": {}, "version_links": {"t1": [B.norm(g.stem)]},
        "version_files": {"t1": [str(g)]}}
assert st(cfg2) != "missing"
print("ok usar_version")
