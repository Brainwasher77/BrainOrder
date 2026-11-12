"""Unificar solo aparta la MISMA grabación (misma regla que Recuperar): dos versiones con 4,5 s de diferencia
(Robert Miles - Children, ISRC distinto) no se apartan; si no, Recuperar la devolvía y Unificar la volvía a
apartar en cada vuelta."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import unificar, biblioteca as b
unificar.rb_index = lambda progress=None: {}
b.save_durations = lambda: None
root = Path(tempfile.mkdtemp())
d = root / "lib"
for f in ("Pop", "Shazam"):
    (d / f).mkdir(parents=True)
a, c = d / "Pop" / "Robert Miles - Children.mp3", d / "Shazam" / "Robert Miles - Children.mp3"
a.write_bytes(b"a" * 300); c.write_bytes(b"c" * 200)
DUR = {}
b.duration = lambda p: DUR.get(str(p))
DUR.update({str(a): 246.73, str(c): 242.26})
pl = unificar.plan({"dest_root": str(d)}, analysis=[])
assert pl["dups"] == [], pl["dups"]
DUR[str(c)] = 245.9  # ahora sí es la misma grabación (0,8 s)
pl = unificar.plan({"dest_root": str(d)}, analysis=[])
assert len(pl["dups"]) == 1, pl["dups"]
shutil.rmtree(root)
print("OK")
