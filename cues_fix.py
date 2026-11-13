"""Cues corridos: mover los cues de Rekordbox para que caigan sobre la grilla.

Caso de Frank (13 nov 2026): 9.248 canciones (95 % MP3) con TODOS sus hot cues 20–50 ms antes de la grilla. Él miró
«Stereo MC's - Fade Away» en Rekordbox: la grilla está sobre el kick y el cue un poco antes → la grilla está bien y
los cues corridos. Vienen de Mixed In Key: cada programa cuenta distinto el arranque de un MP3 (el retardo del
codificador), así que los cues de MIK caen unos ms antes en Rekordbox.

Regla (la misma con la que Grillas dudosas marca «cues»): si los cues que están cerca de un tiempo de la grilla caen
corridos igual (≥ SHIFT_MS, con ≤ 15 ms de diferencia entre ellos), cada uno de esos se pone exactamente sobre su
tiempo; los demás (los que estaban a propósito en otro lado) se corren lo mismo (la mediana). Loops: el final se
mueve igual que el inicio. Un solo cue (≥ 25 ms fuera, «Un cue fuera»): se pone sobre su tiempo, como haría la
cuantización de Rekordbox (13 nov 2026, después de que Frank confirmara la regla con los cues de varias canciones). Solo cambia la base de datos (djmdCue y su copia contentCue); la grilla no se toca.
"""
import bisect
import statistics

SHIFT_MS = 15
MAX_MS = 80


def _near(times, c):
    i = bisect.bisect_left(times, c)
    cand = [times[j] for j in (i - 1, i) if 0 <= j < len(times)]
    if not cand:
        return None, None
    near = min(cand, key=lambda t: abs(t - c))
    j = times.index(near)
    period = abs(times[j + 1] - near) if j + 1 < len(times) else (abs(near - times[j - 1]) if j else 500)
    return near, period


def plan(grid, cues, single=True):
    """grid [(n, bpm, ms)], cues [(id, InMsec, OutMsec)] -> (mediana, [(id, in_nuevo, out_nuevo)]) o (None, [])."""
    times = [g[2] for g in grid]
    if len(times) < 2:
        return None, []
    offs = {}
    for cid, a, _b in cues:
        if a is None or a < 0:
            continue
        near, period = _near(times, a)
        if near is None:
            continue
        off = a - near
        if abs(off) <= min(MAX_MS, period * 0.3):
            offs[cid] = (off, near)
    shifted = [o for o, _ in offs.values() if abs(o) >= SHIFT_MS]
    live = [c for c in cues if c[1] is not None and c[1] >= 0]
    if single and len(live) == 1 and len(offs) == 1:
        cid, a, b = live[0]
        off, near = offs.get(cid, (0, None))
        if abs(off) < 25:
            return None, []
        new_b = b + (near - a) if (b is not None and b > a) else b
        return off, [(cid, int(near), new_b)]
    if len(shifted) < 2 or len(shifted) < 0.6 * len(offs) or max(shifted) - min(shifted) > 15:
        return None, []
    med = statistics.median(shifted)
    out = []
    for cid, a, b in cues:
        if a is None or a < 0:
            continue
        if cid in offs and abs(offs[cid][0] - med) <= 15:
            new_a = offs[cid][1]  # justo sobre su tiempo
        else:
            new_a = int(round(a - med))
        delta = new_a - a
        new_b = b + delta if (b is not None and b > a) else b
        if delta:
            out.append((cid, max(0, int(new_a)), new_b))
    return med, out
