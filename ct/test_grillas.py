"""Pruebas de grillas.py con audio sintético (kicks en posiciones conocidas) y un ANLZ armado a mano."""
import array
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import grillas as G  # noqa: E402


def anlz(grid):
    """ANLZ*.DAT mínimo con un PQTZ (y otro bloque antes, para probar que se salta)."""
    other = b"PPTH" + (16).to_bytes(4, "big") + (20).to_bytes(4, "big") + b"\0" * 8
    body = b"".join(b.to_bytes(2, "big") + int(round(t * 100)).to_bytes(2, "big") + int(ms).to_bytes(4, "big")
                    for b, t, ms in grid)
    pq = b"PQTZ" + (24).to_bytes(4, "big") + (24 + len(body)).to_bytes(4, "big") + b"\0" * 4 \
        + (0x80000).to_bytes(4, "big") + len(grid).to_bytes(4, "big") + body
    data = other + pq
    return b"PMAI" + (28).to_bytes(4, "big") + (28 + len(data)).to_bytes(4, "big") + b"\0" * 16 + data


def make_grid(bpm, first_ms, dur_ms, first_num=1):
    p = 60000.0 / bpm
    out, k = [], 0
    while first_ms + k * p < dur_ms:
        out.append(((first_num - 1 + k) % 4 + 1, bpm, int(round(first_ms + k * p))))
        k += 1
    return out


def make_audio(bpm, first_ms, dur_ms, intro_hats=True, seed=1):
    """Kicks (55 Hz que cae) cada tiempo desde first_ms; hi-hats agudos en los contratiempos; ruido."""
    rnd = random.Random(seed)
    n = int(dur_ms * G.SR / 1000)
    a = [rnd.uniform(-300, 300) for _ in range(n)]
    p = 60000.0 / bpm
    t = first_ms
    while t < dur_ms:
        s = int(t * G.SR / 1000)
        for i in range(int(0.12 * G.SR)):
            if s + i < n:
                a[s + i] += 12000 * math.exp(-i / (0.03 * G.SR)) * math.sin(2 * math.pi * 55 * i / G.SR)
        h = int((t + p / 2) * G.SR / 1000)
        for i in range(int(0.02 * G.SR)):
            if h + i < n:
                a[h + i] += rnd.uniform(-4000, 4000) * math.exp(-i / (0.004 * G.SR))
        t += p
    return array.array("h", [max(-32768, min(32767, int(x))) for x in a])


def run(audio, grid, ext=".wav", calib=None):
    G.decode = lambda path, dec, timeout=180: audio
    m = G.measure("x" + ext, grid, ("fake", ""))
    return m, G.audio_reasons(m, ext, calib or {ext: 0.0})


def codes(why):
    return sorted(w["c"] for w in why)


def test():
    # 1) leer el PQTZ
    g = make_grid(128, 500, 30000)
    got = G.parse_pqtz(anlz(g))
    assert got == [(b, round(t, 2), ms) for b, t, ms in g], got[:3]
    assert G.parse_pqtz(b"nada") == []

    dur = 200000
    audio = make_audio(128, 1000, dur)
    # 2) grilla bien puesta: nada que decir
    m, why = run(audio, make_grid(128, 1000, dur))
    assert not m.get("unclear"), m
    assert abs(m["off"]) < 8, m
    assert codes(why) == [], why
    # 3) grilla corrida 40 ms (la grilla va antes del kick -> el kick cae después)
    m, why = run(audio, make_grid(128, 960, dur))
    assert "shift" in codes(why), (m, why)
    assert 30 <= m["off"] <= 50, m
    # 4) BPM un poquito mal (128.05): al final se corre
    m, why = run(audio, make_grid(128.05, 1000, dur))
    assert "drift" in codes(why), (m, why)
    # 5) el «1» puesto en el tiempo 3: el primer kick no cae en el 1
    m, why = run(audio, make_grid(128, 1000, dur, first_num=3))
    assert "down" in codes(why), (m, why)
    # 5b) grilla en el contratiempo (media negra corrida)
    m, why = run(audio, make_grid(128, 1000 + 234.375, dur))
    assert codes(why) == ["offbeat"], (m, why)
    # 6) calibración: si todas las de un tipo vienen corridas igual, es el decodificador, no la grilla
    m, why = run(audio, make_grid(128, 974, dur), ext=".mp3", calib={".mp3": 26.0})
    assert "shift" not in codes(why), (m, why)
    assert G.calibration([(".mp3", {"off": x}) for x in (25, 26, 27, 26, 80, 24)]) == {".mp3": 26.0}
    # sin calibrar (pocas medidas): solo lo evidente (≥35 ms)
    assert G.audio_reasons({"off": 25.0}, ".mp3", {}) == []
    # 7) sin kicks claros (solo ruido): no se juzga
    G.decode = lambda path, dec, timeout=180: array.array("h", [random.randint(-300, 300) for _ in range(G.SR * 90)])
    m = G.measure("x.wav", make_grid(128, 1000, 90000), ("fake", ""))
    assert m.get("unclear"), m

    # 8) revisiones rápidas
    base = {"id": "1", "path": "/a.mp3", "title": "t", "artist": "a", "genre": "", "pls": [], "len": 300, "cues": []}
    t = dict(base, grid=[])
    assert codes(G.check(t)) == ["nogrid"]
    t = dict(base, genre="Reggaeton", grid=make_grid(190, 100, 60000))
    assert codes(G.check(t)) == ["double"], G.check(t)
    t = dict(base, pls=["Techno oscuro"], grid=make_grid(64, 100, 60000))
    assert codes(G.check(t)) == ["half"], G.check(t)
    t = dict(base, genre="House", grid=make_grid(127.8, 100, 60000))
    assert codes(G.check(t)) == ["dec"], G.check(t)
    t = dict(base, genre="House", grid=make_grid(127.98, 100, 60000))  # centésimas: Rekordbox suele tener razón
    assert codes(G.check(t)) == [], G.check(t)
    t = dict(base, genre="Salsa", grid=make_grid(96.43, 100, 60000))  # en vivo: decimales normales
    assert codes(G.check(t)) == [], G.check(t)
    t = dict(base, grid=make_grid(172, 100, 60000))
    assert codes(G.check(t, mik_bpm=86)) == ["double"]
    assert codes(G.check(t, mik_bpm=170)) == ["mik"]
    assert codes(G.check(t, mik_bpm=172)) == []
    gr = make_grid(128, 100, 60000)
    t = dict(base, grid=gr, cues=[gr[8][2] + 30, gr[40][2] + 33, gr[72][2] + 28])
    assert codes(G.check(t)) == ["cues"], G.check(t)
    t = dict(base, grid=gr, cues=[gr[8][2], gr[40][2] + 2])  # en la grilla
    assert codes(G.check(t)) == []
    t = dict(base, grid=gr, cues=[gr[8][2] + 234])  # en el contratiempo a propósito: no cuenta
    assert codes(G.check(t)) == []
    var = make_grid(128, 100, 30000) + [(1, 129.5, 30100 + i * 463) for i in range(20)]
    assert codes(G.check(dict(base, genre="Tech House", grid=var))) == ["var"]
    assert G.signature(gr) != G.signature(make_grid(128, 110, 60000))
    print("ok")


if __name__ == "__main__":
    test()
