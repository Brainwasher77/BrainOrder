"""grillas.check: Mixed In Key manda sobre el rango del estilo, sin ir y volver (doble ↔ mitad)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grillas as G  # noqa: E402


def c(bpm, mik, hint):
    t = {"grid": [(1, bpm, 0), (2, bpm, 500)], "genre": hint, "pls": [], "cues": []}
    return [w["c"] for w in G.check(t, mik) if w["c"] in ("double", "half", "mik")]


assert c(172, 172, "Reggaeton Clasico ADC") == []      # MIK de acuerdo: el rango del estilo ya no la marca
assert c(86, 172, "reggaeton") == []                   # Rekordbox en el rango y MIK no: se deja (no rebota)
assert c(160, 80, "Hard Techno") == []                 # hard techno 160 bien aunque MIK diga 80
assert c(80, 160, "Hard Techno") == ["half"]
assert c(180, 90, "Salsa") == ["double"] and c(77, 154, "Pop") == ["half"]
assert c(172, None, "reggaeton") == ["double"]         # sin MIK, el rango del estilo
assert c(128, 131, "house") == ["mik"]
# lo que se marca, una vez corregido, ya no se vuelve a marcar
for bpm, mik, hint in ((180, 90, "Salsa"), (77, 154, "Pop"), (80, 160, "Hard Techno"), (172, None, "reggaeton")):
    k = c(bpm, mik, hint)[0]
    assert c(bpm / 2 if k == "double" else bpm * 2, mik, hint) == [], (bpm, mik, hint)
print("ok test_grillas_mik")
