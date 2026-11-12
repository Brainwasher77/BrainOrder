"""Carpetas repetidas: una carpeta que agrupa playlists (con subcarpetas) o sin canciones no se «junta»;
«X» y «X ADC» son playlists distintas; una carpeta con solo accesos directos sale como vacía."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import unificar, biblioteca as b
unificar.rb_index = lambda progress=None: {}
root = Path(tempfile.mkdtemp())
d = root / "lib"
for f in ("Brainwasher/Hard", "Brainwasher/Soft", "Brainwasher🚀", "Rumba internacional", "Rumba Internacional ADC",
          "Stay High", "Stay High🌒", "Otra"):
    (d / f).mkdir(parents=True)
for f in ("Brainwasher/Hard/a.mp3", "Brainwasher🚀/b.mp3", "Rumba internacional/c.mp3", "Stay High/d.mp3",
          "Stay High🌒/e.mp3", "Stay High🌒/f.mp3", "Otra/g.mp3"):
    (d / f).write_bytes(b"x" * 100)
os.symlink("../Otra/g.mp3", d / "Rumba Internacional ADC" / "g.mp3")
assert not b.similar_folders("Rumba internacional", "Rumba Internacional ADC")
assert b.similar_folders("Stay High", "Stay High🌒")
pl = unificar.plan({"dest_root": str(d)}, analysis=[])
merges = [(Path(m["target"]).name, [Path(s["folder"]).name for s in m["sources"]]) for m in pl["merges"]]
assert merges == [("Stay High🌒", ["Stay High"])], merges
assert [Path(x).name for x in pl["empty"]] == ["Rumba Internacional ADC"], pl["empty"]
unificar.apply(pl, {"dest_root": str(d)}, [m["id"] for m in pl["merges"]], [], True)
assert not (d / "Rumba Internacional ADC").exists() and (d / "Otra" / "g.mp3").exists()  # el enlace, no la canción
assert (d / "Brainwasher" / "Hard" / "a.mp3").exists() and (d / "Stay High🌒" / "d.mp3").exists()
shutil.rmtree(root)
print("OK")
