"""anlz_bpm + API bpm_fix: BPM al doble corregido directo en los ANLZ de Rekordbox (÷2), con respaldo y deshacer."""
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import anlz_bpm as A  # noqa: E402


def tag(name, head_extra, body):
    lh = 12 + len(head_extra)
    return name + struct.pack(">II", lh, lh + len(body)) + head_extra + body


def pmai(*tags):
    head = b"PMAI" + struct.pack(">II", 28, 0) + b"\0" * 16
    body = b"".join(tags)
    h = bytearray(head)
    struct.pack_into(">I", h, 8, len(head) + len(body))
    return bytes(h) + body


def make(first_beat=4, n=16, tempo=18000, t0=159):
    per = 60000 / (tempo / 100)
    beats = [((first_beat - 1 + k) % 4 + 1, tempo, int(round(t0 + k * per))) for k in range(n)]
    pqtz = tag(b"PQTZ", struct.pack(">III", 0, 0x80000, len(beats)), b"".join(struct.pack(">HHI", *b) for b in beats))
    ppth = tag(b"PPTH", struct.pack(">I", 8), "/a.mp3".encode("utf-16-be"))
    dat = pmai(ppth, pqtz)
    ents = b"".join(struct.pack(">H", (100 + 300 * k) % 1000) for k in range(n))
    h2 = (struct.pack(">I", 0) + struct.pack(">I", 0x1000002) + struct.pack(">I", 0)
          + struct.pack(">HHI", *beats[0]) + struct.pack(">HHI", *beats[-1]) + struct.pack(">IIII", n, 7, 0, 0))
    pqt2 = tag(b"PQT2", h2, ents)
    pwv = tag(b"PWV5", struct.pack(">II", 2, 0), b"\x11\x22\x33\x44")
    ext = pmai(ppth, pqt2, pwv)
    return dat, ext, beats


dat, ext, beats = make()
d2, e2, bpm, n = A.halve(dat, ext)
nb = A.read_beats(d2)
assert bpm == 90.0 and n == 8 and len(nb) == 8, (bpm, n)
assert nb[0] == (1, 9000, beats[1][2]), nb[0]  # arranca en el primer «1» (el segundo tiempo de la grilla)
assert [b[0] for b in nb] == [1, 2, 3, 4, 1, 2, 3, 4]
assert [b[2] for b in nb] == [b[2] for b in beats[1::2]]
assert struct.unpack(">I", d2[8:12])[0] == len(d2)  # largo del archivo en la cabecera
# PQT2: cabecera con el primero y el último nuevos, entradas de la misma mitad, el resto del .EXT igual
_, t2 = A._tags(e2)
names = [t for t, _ in t2]
assert names == [b"PPTH", b"PQT2", b"PWV5"], names
q = dict(t2)[b"PQT2"]
lh = struct.unpack(">I", q[4:8])[0]
assert struct.unpack(">HHI", q[24:32]) == nb[0] and struct.unpack(">HHI", q[32:40]) == nb[-1]
assert struct.unpack(">I", q[40:44])[0] == 8
assert [struct.unpack(">H", q[lh + 2 * k:lh + 2 * k + 2])[0] for k in range(8)] == [(100 + 300 * k) % 1000 for k in range(1, 16, 2)]
assert struct.unpack(">I", q[8:12])[0] == len(q) and dict(t2)[b"PWV5"] == dict(A._tags(ext)[1])[b"PWV5"]
assert struct.unpack(">I", e2[8:12])[0] == len(e2)
# primer tiempo en el 1 / en el 3
assert A.halve_beats([(1, 16200, 17), (2, 16200, 388), (3, 16200, 758), (4, 16200, 1128)])[1] == [(1, 8100, 17), (2, 8100, 758)]
s, nb3 = A.halve_beats([(3, 17000, 0), (4, 17000, 353), (1, 17000, 706), (2, 17000, 1059), (3, 17000, 1412)])
assert s == 0 and nb3 == [(4, 8500, 0), (1, 8500, 706), (2, 8500, 1412)], nb3
# sin .EXT / sin grilla / archivo raro
assert A.halve(dat)[1] is None
for bad in (b"xxxx", pmai(tag(b"PPTH", struct.pack(">I", 0), b""))):
    try:
        A.halve(bad)
        raise AssertionError("debía fallar")
    except A.AnlzError:
        pass
# ×2 (BPM a la mitad): un tiempo nuevo entre cada par; PQT2 con el punto medio circular de las vecinas
dh, eh, bh = make(first_beat=2, n=5, tempo=7700, t0=269)
d3, e3, bpm3, n3 = A.double(dh, eh)
nb2 = A.read_beats(d3)
assert bpm3 == 154.0 and n3 == 9 and nb2[0] == (3, 15400, 269), nb2  # el 2 lento es el 3 rápido
assert [b[0] for b in nb2] == [3, 4, 1, 2, 3, 4, 1, 2, 3]
assert [b[2] for b in nb2[::2]] == [b[2] for b in bh] and nb2[1][2] == round((bh[0][2] + bh[1][2]) / 2)
q = dict(A._tags(e3)[1])[b"PQT2"]
lh = struct.unpack(">I", q[4:8])[0]
assert struct.unpack(">I", q[40:44])[0] == 9 and struct.unpack(">HHI", q[24:32]) == nb2[0] and struct.unpack(">HHI", q[32:40]) == nb2[-1]
assert [struct.unpack(">H", q[lh + 2 * k:lh + 2 * k + 2])[0] for k in range(9)] == [100, 250, 400, 550, 700, 850, 0, 150, 300]
assert A._cmid(990, 10) == 0 and A._cmid(10, 990) == 0 and A._cmid(100, 300) == 200
assert A.fix(dh, eh, 2) == (d3, e3, bpm3, n3) and A.fix(dat, ext, 0.5)[0] == d2
# ÷2 después de ×2 vuelve a la grilla original
assert A.read_beats(A.halve(d3, e3)[0])[0][2] in (bh[0][2], bh[1][2])
print("ok anlz_bpm")

# --- API bpm_fix / bpm_fix_undo con una colección falsa
import app  # noqa: E402
import config  # noqa: E402
import rekordbox_sync  # noqa: E402

root = Path(tempfile.mkdtemp())
rb = root / "rekordbox"
rel = "PIONEER/USBANLZ/abc/1234/ANLZ0000.DAT"
(rb / "share" / rel).parent.mkdir(parents=True)
(rb / "share" / rel).write_bytes(dat)
(rb / "share" / rel).with_suffix(".EXT").write_bytes(ext)
rekordbox_sync.RB_DIR = rb
rekordbox_sync.rekordbox_running = lambda: False
rekordbox_sync.backup = lambda: rb / "master.backup.x.db"
config.SUPPORT_DIR = root / "support"
config.save = lambda c: None
K = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "bpm_fix")][0]
o = K.__new__(K)
o._cfg = {}
o._task = lambda fn, k, l, files=False: {"ok": True, **fn()}
o._progress = lambda *a, **k: None
o._rb_read = lambda fn, tag="": {"1": ("/" + rel, 18000), "9": ("/PIONEER/USBANLZ/x/no/ANLZ0000.DAT", 17000)}
o._grid_tracks = lambda: [{"id": "1", "grid": [(1, 180.0, 0)], "db_bpm": 180.0},
                          {"id": "7", "grid": [(1, 90.0, 0), (2, 90.0, 666)], "db_bpm": 180.0},   # columna al doble
                          {"id": "8", "grid": [(1, 128.0, 0)], "db_bpm": 128.0}]
calls = []
o._bpm_db_write = lambda bpms, files: calls.append((bpms, files))
r = o.bpm_fix(["1", "9", "404"])  # ids sueltos = ÷2
assert r["ok"] and r["done"] == 1 and r["col"] == 1, r
assert {s["id"] for s in r["skipped"]} == {"9", "404"}, r
assert A.read_beats((rb / "share" / rel).read_bytes()) == nb
assert (rb / "share" / rel).with_suffix(".EXT").read_bytes() == e2
bpms, files = calls[0]
assert sorted(bpms) == [("1", 9000), ("7", 9000)] and files == [("/" + rel, d2, e2)], calls
bdir = Path(r["backup"])
assert (bdir / rel).read_bytes() == dat and (bdir / rel).with_suffix(".EXT").read_bytes() == ext
m = json.loads((bdir / "manifest.json").read_text("utf-8"))
assert m["items"][0]["bpm0"] == 18000 and m["col"][0]["id"] == "7"
assert o.bpm_fix_state()["last"]["n"] == 1
# Rekordbox abierto -> no toca nada
rekordbox_sync.rekordbox_running = lambda: True
try:
    o.bpm_fix(["1"])
    raise AssertionError("debía pedir cerrar Rekordbox")
except rekordbox_sync.RekordboxError:
    pass
rekordbox_sync.rekordbox_running = lambda: False
# deshacer
calls.clear()
u = o.bpm_fix_undo()
assert u["undone"] == 1 and (rb / "share" / rel).read_bytes() == dat and (rb / "share" / rel).with_suffix(".EXT").read_bytes() == ext
assert sorted(calls[0][0]) == [("1", 18000), ("7", 18000)] and calls[0][1] == [("/" + rel, dat, ext)]
assert o.bpm_fix_state()["last"] is None
# ×2 por la API ({id, f: 2}) y columna BPM a la mitad
rel2 = "PIONEER/USBANLZ/abc/5678/ANLZ0000.DAT"
(rb / "share" / rel2).parent.mkdir(parents=True)
(rb / "share" / rel2).write_bytes(dh)
(rb / "share" / rel2).with_suffix(".EXT").write_bytes(eh)
o._rb_read = lambda fn, tag="": {"2": ("/" + rel2, 7700)}
o._grid_tracks = lambda: [{"id": "5", "grid": [(1, 154.0, 0), (2, 154.0, 390)], "db_bpm": 77.0}]
calls.clear()
r2 = o.bpm_fix([{"id": "2", "f": 2}])
assert r2["done"] == 1 and r2["doubled"] == 1 and r2["col"] == 1, r2
assert (rb / "share" / rel2).read_bytes() == d3 and sorted(calls[0][0]) == [("2", 15400), ("5", 15400)], calls
o.bpm_fix_undo()
assert (rb / "share" / rel2).read_bytes() == dh and sorted(calls[-1][0]) == [("2", 7700), ("5", 7700)]
o._rb_read = lambda fn, tag="": {"1": ("/" + rel, 18000)}
o._grid_tracks = lambda: []
# si falla la base de datos, los ANLZ vuelven a como estaban
def boom(*a):
    raise RuntimeError("db bloqueada")
o._bpm_db_write = boom
try:
    o.bpm_fix(["1"])
    raise AssertionError("debía fallar")
except rekordbox_sync.RekordboxError:
    pass
assert (rb / "share" / rel).read_bytes() == dat and (rb / "share" / rel).with_suffix(".EXT").read_bytes() == ext
print("ok api bpm_fix")
