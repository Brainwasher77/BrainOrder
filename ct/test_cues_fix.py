"""cues_fix.plan: cues corridos igual respecto a la grilla -> justo sobre su tiempo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cues_fix as C  # noqa: E402
import grillas  # noqa: E402

per = 60000 / 124
grid = [((k % 4) + 1, 124.0, int(round(157 + k * per))) for k in range(400)]
T = [g[2] for g in grid]
# 8 cues de MIK 44 ms antes de sus tiempos (con ±3 ms de ruido) + uno a propósito en el contratiempo
cues = [(str(i), T[b] - 44 + (i % 3 - 1) * 3, -1) for i, b in enumerate((3, 67, 115, 227, 291, 339, 387, 120))]
cues.append(("x", T[50] + int(per / 2), -1))
med, ch = C.plan(grid, cues)
assert -47 <= med <= -41, med
new = {i: a for i, a, _ in ch}
for i, b in enumerate((3, 67, 115, 227, 291, 339, 387, 120)):
    assert new[str(i)] == T[b], (i, new[str(i)], T[b])  # justo sobre su tiempo
assert new["x"] == int(round(T[50] + int(per / 2) - med))  # el del contratiempo se corre lo mismo
assert grillas.cue_offsets(grid, [new[str(i)] for i in range(8)]) == [0] * 8
# loop: el final se mueve igual
med, ch = C.plan(grid, [("a", T[10] - 30, T[18] - 30), ("b", T[20] - 30, -1), ("c", T[30] - 31, -1)])
d = {i: (a, b) for i, a, b in ch}
assert d["a"] == (T[10], T[18]) and d["b"] == (T[20], -1)
# bien puestos / dispersos / uno solo / sin grilla -> nada
assert C.plan(grid, [("a", T[1] + 2, -1), ("b", T[9] - 3, -1)]) == (None, [])
assert C.plan(grid, [("a", T[1] - 20, -1), ("b", T[9] - 50, -1)]) == (None, [])
assert C.plan(grid, [("a", T[1] - 40, -1)]) == (-40, [("a", T[1], -1)])          # un solo cue: sobre su tiempo
assert C.plan(grid, [("a", T[1] + 61, -1)]) == (61, [("a", T[1], -1)])
assert C.plan(grid, [("a", T[1] - 20, -1)]) == (None, [])                       # < 25 ms: se deja
assert C.plan(grid, [("a", T[1] - 40, -1)], single=False) == (None, [])
assert C.plan(grid, [("a", T[1] + int(per / 2), -1)]) == (None, [])             # en el contratiempo: a propósito
assert C.plan([], [("a", 100, -1), ("b", 200, -1)]) == (None, [])
# coincide con lo que Grillas dudosas marca como «cues»
w = grillas.check({"grid": grid, "genre": "", "pls": [], "cues": [a for _, a, _ in cues]})
assert any(x["c"] == "cues" for x in w), w
print("ok test_cues_fix")
