"""2.53.0: detalles de los archivos para las columnas (género, año, bitrate, tamaño…), con caché."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import detalles as D  # noqa: E402

d = Path(tempfile.mkdtemp())
f = d / "x.mp3"
f.write_bytes(b"\0" * 2048)  # no es audio de verdad: no debe romper
D.load(d / "detalles.json")
i = D.info(str(f))
assert i["size"] == 2048 and i["ext"] == "mp3" and i["added"] > 0 and i["genre"] == "", i
assert D._year("2019-05-01") == 2019 and D._year("") is None and D._num("3/12") == 3
try:
    from mutagen.id3 import ID3, TCON, TDRC, TALB
    g = d / "y.mp3"
    g.write_bytes(b"\0" * 1024)
    t = ID3()
    t.add(TCON(encoding=3, text="Techno"))
    t.add(TDRC(encoding=3, text="2004"))
    t.add(TALB(encoding=3, text="Disco"))
    t.save(str(g))
    j = D.info(str(g))
    assert j["genre"] == "Techno" and j["year"] == 2004 and j["album"] == "Disco", j
except ImportError:
    pass
out = D.many([str(f), str(f), str(d / "no.mp3")])
assert list(out) == [str(f)]
assert (d / "detalles.json").exists()
print("ok detalles")
