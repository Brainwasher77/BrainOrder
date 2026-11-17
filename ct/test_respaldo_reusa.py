"""Si la librería no cambió desde el último respaldo, se reutiliza (no se copia otra vez ni se saca uno viejo)."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import rekordbox_sync as RS
from destinos import traktor
d = Path(tempfile.mkdtemp())
RS.RB_DIR = d
(d / "master.db").write_bytes(b"x" * 100)
old = time.time() - 120
os.utime(d / "master.db", (old, old))
b1 = RS.backup()
b2 = RS.backup()
assert b1 == b2 and len(list(d.glob("master.backup.brainorder-*.db"))) == 1, (b1, b2)
time.sleep(1.1)
(d / "master.db").write_bytes(b"y" * 100)  # cambió: respaldo nuevo
time.sleep(1.1)
b3 = RS.backup()
assert b3 != b1 and b3.read_bytes() == b"y" * 100, b3
# Traktor igual
c = d / "collection.nml"; c.write_text("<NML/>"); os.utime(c, (old, old))
n1 = traktor.backup(c); n2 = traktor.backup(c)
assert n1 == n2 and len(list(d.glob("collection.brainorder-*.nml.bak"))) == 1
print("OK")
