"""2.52.0: la ruta de los ANLZ se cambia tocando solo la etiqueta PPTH (sin interpretar el archivo entero)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rb_coleccion as RC  # noqa: E402


def ppth(p):
    enc = p.encode("utf-16-be") + b"\0\0"
    return b"PPTH" + (16).to_bytes(4, "big") + (16 + len(enc)).to_bytes(4, "big") + len(enc).to_bytes(4, "big") + enc


def anlz(path, extra=b""):
    pq = b"PQTZ" + (24).to_bytes(4, "big") + (24 + 8).to_bytes(4, "big") + b"\0" * 4 + (0x80000).to_bytes(4, "big") \
        + (1).to_bytes(4, "big") + (1).to_bytes(2, "big") + (12800).to_bytes(2, "big") + (500).to_bytes(4, "big")
    data = ppth(path) + pq + extra
    return b"PMAI" + (28).to_bytes(4, "big") + (28 + len(data)).to_bytes(4, "big") + b"\0" * 16 + data


d = Path(tempfile.mkdtemp())
f = d / "ANLZ0000.DAT"
f.write_bytes(anlz("/Users/f/Music/Viejo/Canción ñ.mp3", b"PWV5" + (12).to_bytes(4, "big") + (12 + 4000).to_bytes(4, "big") + os.urandom(4000)))
new = "/Users/f/Music/BRAIN LIBRARY/Organizar/Canción ñ — nueva.mp3"
assert RC.ppth_set(str(f), new) is True
b = f.read_bytes()
assert b == anlz(new, b[-4012:]), "bytes distintos a un ANLZ hecho con la ruta nueva"
assert int.from_bytes(b[8:12], "big") == len(b)
assert RC.ppth_set(str(f), new) is False  # ya estaba
try:  # comparar con pyrekordbox si está
    from pyrekordbox.anlz import AnlzFile
    g = d / "ANLZ0000.EXT"
    g.write_bytes(anlz("/a/b.mp3"))
    a = AnlzFile.parse_file(str(g))
    a.set_path(new)
    ref = a.build()
    RC.ppth_set(str(g), new)
    assert g.read_bytes() == ref, "distinto a pyrekordbox"
    assert AnlzFile.parse_file(str(g)).get("path") == new
    print("igual que pyrekordbox")
except ImportError:
    pass
# «?/nombre» se respeta
h = d / "ANLZ0000.2EX"
h.write_bytes(anlz("?/viejo.mp3"))
RC.ppth_set(str(h), new)
assert RC.ppth_set(str(h), "/x/Canción ñ — nueva.mp3") is False
# write_anlz con muchas: rápido
files = []
for i in range(3000):
    p = d / f"x{i}" / "ANLZ0000.DAT"
    p.parent.mkdir()
    p.write_bytes(anlz(f"/v/{i}.mp3", b"PWV5" + (12).to_bytes(4, "big") + (12 + 50000).to_bytes(4, "big") + b"\1" * 50000))
    files.append(([str(p)], f"/n/{i}.mp3"))
t0 = time.time()
RC.write_anlz(files)
dt = time.time() - t0
assert (d / "x7" / "ANLZ0000.DAT").read_bytes()[28:].startswith(ppth("/n/7.mp3")), "no cambió"
assert dt < 20, dt
print(f"ok anlz_ppth ({dt:.2f} s para 3000)")
