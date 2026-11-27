"""2.58.3: después de «Cruzando canciones» la barra sigue diciendo qué hace (antes se quedaba en 39760/39772)."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
SUP = TMP / "support"
SUP.mkdir()
config.SUPPORT_DIR = SUP
config.save = lambda c: None
import estructura  # noqa: E402
estructura.SUPPORT_DIR = SUP
import app  # noqa: E402

# _ticker: sin progress no hace nada; con progress, el primero y el forzado salen, el resto espera
assert app._ticker(None, "x", 10)(3) is None
msgs = []
t = app._ticker(msgs.append, "Revisando", 5, every=60)
t(1)
t(2)
t(5, force=True)
assert msgs == ["Revisando: 1/5", "Revisando: 5/5"], msgs
msgs.clear()
t = app._ticker(msgs.append, "R", 3, every=0.01)
t(1)
time.sleep(0.02)
t(2)
assert msgs == ["R: 1/3", "R: 2/3"], msgs
assert app._ticker(msgs.append, "R", 0)(1) is None  # nada que contar: no se dice nada

# estructura.plan avisa playlist por playlist y llega al total
dest = TMP / "dest"
dest.mkdir()
analysis = [{"id": f"p{i}", "name": f"P{i}", "folder": str(dest / f"P{i}"), "tracks": []} for i in range(4)]
seen = []
estructura.plan(analysis, {"dest_root": str(dest)}, tick=lambda i, force=False: seen.append((i, force)))
assert [i for i, _ in seen] == [1, 2, 3, 4] and seen[-1][1] is True, seen
estructura.plan(analysis, {"dest_root": str(dest)})  # sin tick: igual que antes

# biblioteca.analyze termina diciendo el total (antes el último aviso era el múltiplo de 20 anterior)
import biblioteca  # noqa: E402
lib = TMP / "lib"
lib.mkdir()
inbox = TMP / "inbox"
inbox.mkdir()
(lib / "Artista - Uno.mp3").write_bytes(b"x")
tracks = [{"id": f"t{i}", "name": f"Tema {i}", "artists": ["Artista"]} for i in range(23)]
cfg = {"dest_root": str(dest), "inbox": str(inbox), "library_roots": [str(lib)], "rules": {}}
got = []
try:
    biblioteca.analyze([{"id": "pl", "name": "PL", "tracks": tracks}], cfg, lambda m, f=None: got.append(m))
except TypeError:
    biblioteca.analyze([{"id": "pl", "name": "PL", "tracks": tracks}], cfg, lambda m, f=None: got.append(m), alt={})
cross = [m for m in got if m and m.startswith("Cruzando canciones")]
assert cross[-1].startswith("Cruzando canciones: 23/23"), cross
print("avance ok")
