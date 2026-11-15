"""2.51.2: etiquetas de color de Finder en las carpetas de grupo (verde) y «Organizar» (morado)."""
import os
import plistlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import colores as C  # noqa: E402

X = {}  # atributos extendidos falsos: {(ruta, atributo): bytes}


class R:
    def __init__(self, rc, out=""):
        self.returncode, self.stdout = rc, out


def fake(args):
    if args[1] == "-px":
        v = X.get((args[3], args[2]))
        return R(0, v.hex()) if v is not None else R(1)
    X[(args[4], args[2])] = bytes.fromhex(args[3])
    return R(0)


C._run = fake
C.IS_MAC = True
T = Path(tempfile.mkdtemp())
for d in ("Techno/Hard", "Organizar", "Suelta"):
    (T / d).mkdir(parents=True)
X[(str(T / "Techno"), C.TAGS)] = plistlib.dumps(["Trabajo\n4"], fmt=plistlib.FMT_BINARY)  # una etiqueta tuya
n = C.color_groups(T, {"a": ["Techno", "Hard"], "b": ["Organizar"], "c": ["Techno"]}, "Organizar")
assert n == 3, n
tags = lambda p: plistlib.loads(X[(str(T / p), C.TAGS)])
assert tags("Techno") == ["Trabajo\n4", "Verde\n2"] and tags("Techno/Hard") == ["Verde\n2"] and tags("Organizar") == ["Morado\n3"]
assert X[(str(T / "Techno"), C.INFO)][9] == 2 << 1 and X[(str(T / "Organizar"), C.INFO)][9] == 3 << 1
assert (str(T / "Suelta"), C.TAGS) not in X
assert C.color_groups(T, {"a": ["Techno", "Hard"], "b": ["Organizar"]}, "Organizar") == 0  # ya estaban: no se reescribe
C.IS_MAC = False
assert C.color_groups(T, {"a": ["Techno"]}, "") == 0
print("OK")
