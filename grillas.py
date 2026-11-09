"""Grillas dudosas en Rekordbox: canciones cuyo BPM o grilla (beatgrid) probablemente están mal.

Solo LEE: la colección (master.db) y los archivos de análisis de Rekordbox (ANLZ*.DAT, bloque PQTZ =
la grilla: cada tiempo con su número de compás 1-4, su BPM y su posición en ms). No cambia nada.

Revisiones rápidas (toda la colección, sin abrir el audio):
  - sin grilla: Rekordbox no la analizó;
  - BPM al doble o a la mitad: comparado con Mixed In Key o con el rango normal del género / playlist;
  - BPM distinto a Mixed In Key;
  - tus cues caen fuera de la grilla (casi siempre los pusiste en el kick: la grilla está corrida);
  - grilla variable o BPM con decimales en estilos de tempo fijo (house, techno, reguetón…).
Medición del audio (opcional, por canción): decodifica el audio (afconvert en Mac, ffmpeg si está) y
mide dónde caen los kicks respecto a la grilla: corrida al inicio, se va corriendo (BPM no exacto), y si
el primer kick no cae en el «1» del compás.
"""
import array
import bisect
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import unicodedata
import wave
from collections import defaultdict
from pathlib import Path

from config import log
from plataforma import native

SR = 11025          # Hz al decodificar (de sobra para el kick)
HOP = 22            # muestras por cuadro ≈ 2 ms
SHIFT_MS = 20       # desde aquí una grilla corrida se nota al mezclar
VERSION = 1         # de la medición guardada en caché

# rango normal de BPM por estilo (para detectar el doble / la mitad). Solo estilos donde no hay duda.
RANGES = [
    ("reguetón", ("reggaeton", "regueton", "reggueton", "perreo"), 84, 106),
    ("dembow", ("dembow",), 108, 135),
    ("moombahton", ("moombah",), 98, 116),
    ("house", ("house",), 112, 132),
    ("techno", ("techno",), 120, 152),
    ("trance", ("trance", "psytrance", "psy trance"), 125, 150),
    ("drum and bass", ("drum and bass", "drum & bass", "drum n bass", "drum'n'bass", "dnb", "jungle"), 158, 182),
    ("hardstyle", ("hardstyle", "hard dance"), 140, 165),
    ("kuduro", ("kuduro",), 125, 145),
    ("dancehall", ("dancehall",), 84, 112),
]
# estilos hechos en computador (tempo fijo): ahí una grilla variable o un BPM con decimales es sospechoso
FIXED = ("electr", "edm", "dance", "house", "techno", "trance", "dnb", "drum and bass", "drum & bass", "dubstep",
         "hardstyle", "garage", "breaks", "minimal", "progressive", "big room", "synth", "trap", "reggaeton",
         "regueton", "reggueton", "perreo", "dembow", "moombah", "kuduro", "dancehall", "afro", "bass",
         "jungle", "hard dance", "psy", "urbano")

SEV = {"nogrid": 3, "double": 3, "half": 3, "mik": 2, "cues": 2, "var": 2, "dec": 1, "cue1": 1,
       "shift": 3, "drift": 3, "down": 2, "offbeat": 3}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


def styles(text):
    t = _norm(text)
    return [(name, lo, hi) for name, keys, lo, hi in RANGES if any(k in t for k in keys)]


def fixed_tempo(text):
    t = _norm(text)
    return any(k in t for k in FIXED)


# ---------------------------------------------------------------- lectura
def parse_pqtz(data):
    """bytes de un ANLZ*.DAT -> [(tiempo 1-4, bpm, ms)] (vacío si no hay grilla)."""
    if len(data) < 12 or data[:4] != b"PMAI":
        return []
    pos = int.from_bytes(data[4:8], "big")
    end = len(data)
    while pos + 12 <= end:
        tag = data[pos:pos + 4]
        lh = int.from_bytes(data[pos + 4:pos + 8], "big")
        lt = int.from_bytes(data[pos + 8:pos + 12], "big")
        if lt <= 0:
            break
        if tag == b"PQTZ":
            n = int.from_bytes(data[pos + 20:pos + 24], "big")
            p = pos + lh
            n = max(0, min(n, (pos + lt - p) // 8))
            out = []
            for i in range(n):
                q = p + i * 8
                out.append((int.from_bytes(data[q:q + 2], "big"), int.from_bytes(data[q + 2:q + 4], "big") / 100.0,
                            int.from_bytes(data[q + 4:q + 8], "big")))
            return out
        pos += lt
    return []


def read_grid(share_dir, anlz_path):
    if not anlz_path:
        return []
    p = Path(share_dir) / str(anlz_path).replace("\\", "/").strip("/")
    try:
        return parse_pqtz(p.read_bytes())
    except OSError:
        return []


def signature(grid):
    """Huella de la grilla: si la corriges en Rekordbox, cambia (y la canción se vuelve a revisar)."""
    if not grid:
        return "0"
    return f"{len(grid)}:{grid[0][2]}:{grid[0][0]}:{grid[0][1]:.2f}:{grid[-1][2]}"


def read_collection(con, share_dir, exists=os.path.exists):
    """-> [{id, path, title, artist, genre, pls, len, cues, grid, sig}] de las pistas cuyo archivo está."""
    rows = con.execute("""SELECT c.ID, c.FolderPath, c.Title, a.Name, g.Name, c.Length, c.AnalysisDataPath, c.BPM
        FROM djmdContent c LEFT JOIN djmdArtist a ON a.ID = c.ArtistID LEFT JOIN djmdGenre g ON g.ID = c.GenreID
        WHERE COALESCE(c.rb_local_deleted, 0) = 0""").fetchall()
    cues = defaultdict(list)
    for cid, ms in con.execute("SELECT ContentID, InMsec FROM djmdCue WHERE COALESCE(rb_local_deleted, 0) = 0"):
        if ms is not None and ms >= 0:
            cues[str(cid)].append(int(ms))
    names = {str(i): n for i, n in con.execute(
        "SELECT ID, Name FROM djmdPlaylist WHERE COALESCE(rb_local_deleted, 0) = 0 AND COALESCE(Attribute, 0) = 0")}
    pls = defaultdict(set)
    for cid, pid in con.execute("SELECT ContentID, PlaylistID FROM djmdSongPlaylist WHERE COALESCE(rb_local_deleted, 0) = 0"):
        if str(pid) in names:
            pls[str(cid)].add(names[str(pid)])
    out = []
    for cid, path, title, artist, genre, length, anlz, bpm in rows:
        cid = str(cid)
        if not path or not exists(native(path)):
            continue  # streaming, perdidas (para eso está «Perdidas») o disco desconectado
        grid = read_grid(share_dir, anlz)
        out.append({"id": cid, "path": path, "title": title or "", "artist": artist or "", "genre": genre or "",
                    "pls": sorted(pls.get(cid, ())), "len": int(length or 0), "cues": sorted(cues.get(cid, [])),
                    "grid": grid, "sig": signature(grid), "db_bpm": (bpm or 0) / 100.0})
    return out


# ---------------------------------------------------------------- revisiones rápidas
def grid_bpm(grid):
    """BPM principal de la grilla (el que más dura)."""
    if not grid:
        return None
    dur = defaultdict(float)
    for i, (_, bpm, ms) in enumerate(grid):
        nxt = grid[i + 1][2] if i + 1 < len(grid) else ms + (60000.0 / bpm if bpm else 0)
        dur[round(bpm, 2)] += max(0.0, nxt - ms)
    return max(dur.items(), key=lambda kv: kv[1])[0]


def cue_offsets(grid, cues):
    """Distancia (ms, con signo) de cada cue al tiempo más cercano de la grilla. Los que están lejos a
    propósito (en un contratiempo) no cuentan."""
    times = [g[2] for g in grid]
    out = []
    for c in cues:
        i = bisect.bisect_left(times, c)
        cand = [times[j] for j in (i - 1, i) if 0 <= j < len(times)]
        if not cand:
            continue
        near = min(cand, key=lambda t: abs(t - c))
        j = times.index(near)
        period = abs(times[j + 1] - near) if j + 1 < len(times) else (abs(near - times[j - 1]) if j else 500)
        off = c - near
        if abs(off) <= min(80, period * 0.3):
            out.append(off)
    return out


def _fmt(b):
    return f"{b:.2f}".rstrip("0").rstrip(".") if b else "?"


def check(t, mik_bpm=None):
    """-> lista de motivos [{c, t, s}] (c = código, t = texto, s = gravedad 1-3) para la pista t."""
    grid, why = t["grid"], []

    def add(code, text):
        why.append({"c": code, "t": text, "s": SEV[code]})
    if not grid:
        add("nogrid", "Sin grilla: Rekordbox no la ha analizado")
        return why
    bpm = grid_bpm(grid)
    hint = " ".join([t.get("genre") or ""] + list(t.get("pls") or []))
    sty, fixed = styles(hint), fixed_tempo(hint)
    tempo_done = False
    if mik_bpm:
        r = bpm / mik_bpm
        if abs(r - 2) < 0.04:
            add("double", f"BPM al doble: Rekordbox {_fmt(bpm)}, Mixed In Key {_fmt(mik_bpm)}")
            tempo_done = True
        elif abs(r - 0.5) < 0.01:
            add("half", f"BPM a la mitad: Rekordbox {_fmt(bpm)}, Mixed In Key {_fmt(mik_bpm)}")
            tempo_done = True
        elif abs(bpm - mik_bpm) > 0.6:
            add("mik", f"BPM distinto: Rekordbox {_fmt(bpm)}, Mixed In Key {_fmt(mik_bpm)}")
            tempo_done = True
    if not tempo_done and sty and not any(lo <= bpm <= hi for _, lo, hi in sty):
        for name, lo, hi in sty:
            if lo <= bpm * 2 <= hi:
                add("half", f"BPM a la mitad: {_fmt(bpm)}; en {name} lo normal es {lo}–{hi} (¿{_fmt(bpm * 2)}?)")
                break
            if lo <= bpm / 2 <= hi:
                add("double", f"BPM al doble: {_fmt(bpm)}; en {name} lo normal es {lo}–{hi} (¿{_fmt(bpm / 2)}?)")
                break
    tempos = [g[1] for g in grid if g[1]]
    variable = bool(tempos) and max(tempos) - min(tempos) > 0.1
    if fixed and variable:
        add("var", f"Grilla variable ({_fmt(min(tempos))}–{_fmt(max(tempos))}) en un estilo de tempo fijo: "
                   "¿quedó en modo Dinámico?")
    elif fixed and abs(bpm - round(bpm)) >= 0.01:
        add("dec", f"BPM {_fmt(bpm)} con decimales en un estilo de tempo fijo (¿{round(bpm)}?)")
    offs = cue_offsets(grid, t.get("cues") or [])
    off = [o for o in offs if abs(o) >= SHIFT_MS]
    if len(off) >= 2 and len(off) >= 0.6 * len(offs) and max(off) - min(off) <= 15:
        m = statistics.median(off)
        add("cues", f"Tus {len(off)} cues caen {abs(m):.0f} ms {'después' if m > 0 else 'antes'} de la grilla: "
                    "la grilla está corrida")
    elif len(offs) == 1 and abs(offs[0]) >= 25:
        add("cue1", f"Tu cue cae {abs(offs[0]):.0f} ms {'después' if offs[0] > 0 else 'antes'} de la grilla")
    return why


def item(t, why, mik_bpm=None):
    return {"id": t["id"], "path": t["path"], "title": t["title"], "artist": t["artist"], "genre": t["genre"],
            "pls": t["pls"][:6], "npl": len(t["pls"]), "len": t["len"], "bpm": grid_bpm(t["grid"]),
            "mik_bpm": mik_bpm, "sig": t["sig"], "ext": os.path.splitext(t["path"])[1].lower(),
            "why": why, "sev": max((w["s"] for w in why), default=0)}


def summary(items):
    s = defaultdict(int)
    for x in items:
        for w in x["why"]:
            s[w["c"]] += 1
    return dict(s)


# ---------------------------------------------------------------- medición del audio
def decoder():
    """('afconvert'|'ffmpeg', ruta) o None."""
    if sys.platform == "darwin" and os.path.exists("/usr/bin/afconvert"):
        return ("afconvert", "/usr/bin/afconvert")
    for c in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if c and os.path.exists(c):
            return ("ffmpeg", c)
    return None


def decode(path, dec, timeout=180):
    """Audio -> array('h') mono a SR Hz (o None)."""
    tmp = Path(tempfile.mkdtemp(prefix="brainorder-grid-"))
    dst = tmp / "a.wav"
    try:
        kind, exe = dec
        if kind == "afconvert":
            args = [exe, "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", native(path), str(dst)]
        else:
            args = [exe, "-v", "error", "-nostdin", "-y", "-i", native(path), "-ac", "1", "-ar", str(SR),
                    "-f", "wav", "-acodec", "pcm_s16le", str(dst)]
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        r = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout, **kw)
        if r.returncode != 0 or not dst.exists():
            log(f"grillas: no pude decodificar {path}: {r.stderr[-300:]!r}")
            return None
        with wave.open(str(dst), "rb") as w:
            if w.getsampwidth() != 2 or w.getframerate() != SR:
                return None
            ch = w.getnchannels()
            a = array.array("h")
            a.frombytes(w.readframes(w.getnframes()))
        if sys.byteorder != "little":
            a.byteswap()
        if ch > 1:
            a = array.array("h", a[::ch])
        return a
    except Exception as e:
        log(f"grillas: error decodificando {path}: {e!r}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def onset(samples, s0, s1):
    """Fuerza de ataque en graves (kick) por cuadro de HOP muestras, desde la muestra s0 hasta s1."""
    s0, s1 = max(0, s0), min(len(samples), s1)
    a = 1 - math.exp(-2 * math.pi * 110 / SR)
    y1 = y2 = 0.0
    # se precalienta el filtro 50 ms antes para no inventar un ataque al inicio de la ventana
    for x in samples[max(0, s0 - 550):s0]:
        y1 += a * (x - y1)
        y2 += a * (y1 - y2)
    env, acc, k = [], 0.0, 0
    for x in samples[s0:s1]:
        y1 += a * (x - y1)
        y2 += a * (y1 - y2)
        acc += y2 * y2
        k += 1
        if k == HOP:
            env.append(math.sqrt(acc / HOP))
            acc, k = 0.0, 0
    return [0.0, 0.0] + [max(0.0, env[i] - env[i - 2]) for i in range(2, len(env))]


def _peaks(o, f0_ms, beats, period_of, shift=0.0):
    """Por cada tiempo de la grilla: el ataque más fuerte a ±70 ms -> [(ms del tiempo, desfase ms, fuerza)]."""
    out, w = [], 35  # cuadros (≈70 ms)
    for i, b in enumerate(beats):
        t = b + shift * period_of(i)
        c = int(round((t - f0_ms) * SR / 1000 / HOP))
        lo, hi = max(0, c - w), min(len(o), c + w + 1)
        if hi - lo < w:
            continue
        j = max(range(lo, hi), key=o.__getitem__)
        out.append((b, (j - c) * HOP * 1000.0 / SR, o[j]))
    return out


def _fit(pts):
    """Recta por mínimos cuadrados de (ms, desfase) -> (desfase en x0, ms de desfase por minuto)."""
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    vx = sum((x - mx) ** 2 for x, _ in pts)
    b = sum((x - mx) * (y - my) for x, y in pts) / vx if vx else 0.0
    return (lambda x: my + b * (x - mx)), b * 60000.0


def _window(samples, grid, a_ms, b_ms):
    """Mide una ventana -> dict(at(ms)=desfase esperado, slope ms/min, mad, contrast, beats) o None."""
    sel = [g for g in grid if a_ms + 80 <= g[2] <= b_ms - 80]
    if len(sel) < 12:
        return None
    s0, s1 = int(a_ms * SR / 1000), int(b_ms * SR / 1000)
    o = onset(samples, s0, s1)
    times = [g[2] for g in sel]

    def period_of(i):
        return (times[i + 1] - times[i]) if i + 1 < len(times) else (times[i] - times[i - 1])
    on = _peaks(o, a_ms, times, period_of)
    mid = _peaks(o, a_ms, times, period_of, 0.5)
    if len(on) < 12 or not mid:
        return None
    st = sorted(p[2] for p in on)
    p75 = st[int(len(st) * 0.75)]
    contrast = statistics.median(p[2] for p in on) / max(1e-6, statistics.median(p[2] for p in mid))
    strong = [p for p in on if p75 > 0 and p[2] >= 0.5 * p75]
    if len(strong) < 10:
        return None
    at, slope = _fit([(b, d) for b, d, _ in strong])
    res = [d - at(b) for b, d, _ in strong]
    mres = statistics.median(res)
    mad = statistics.median(abs(r - mres) for r in res)
    num = {g[2]: g[0] for g in sel}
    return {"at": at, "slope": slope, "mad": mad, "n": len(strong), "contrast": contrast, "p75": p75,
            "first": strong[0][0], "last": strong[-1][0], "mid": statistics.median(d for _, d, _ in strong),
            "beats": [(b, num[b], d, s) for b, d, s in on]}


def _clear(w):
    return w is not None and w["contrast"] >= 1.4 and w["mad"] <= 12


def measure(path, grid, dec, length_s=0):
    """Mide dónde caen los kicks respecto a la grilla. -> dict (ver audio_reasons) o {'err': texto}."""
    if not grid:
        return {"err": "sin grilla"}
    samples = decode(path, dec)
    if samples is None:
        return {"err": "no pude leer el audio"}
    dur = len(samples) * 1000.0 / SR
    first = _window(samples, grid, 0, min(dur, 80000))
    if first is not None and first["contrast"] <= 0.6:
        # entre los tiempos hay ataques mucho más fuertes que en los tiempos: la grilla quedó en el contratiempo
        half = _window(samples, [(b, t, ms + 30000.0 / t) for b, t, ms in grid if t], 0, min(dur, 80000))
        if _clear(half):
            return {"v": VERSION, "offbeat": True, "contrast": round(first["contrast"], 2)}
    if not _clear(first):
        return {"v": VERSION, "unclear": True}
    t0 = first["first"]
    out = {"v": VERSION, "off": round(first["at"](t0), 1), "n": first["n"], "contrast": round(first["contrast"], 2)}
    # primer kick: primer tiempo con un ataque fuerte donde se espera, seguido de otros 3 iguales
    good = [abs(d - first["at"](b)) <= 25 and s >= 0.5 * first["p75"] for b, _, d, s in first["beats"]]
    for i in range(len(good) - 3):
        if all(good[i:i + 4]):
            ms, num, _, _ = first["beats"][i]
            out["kick_ms"], out["kick_beat"] = ms, num
            break
    last = _window(samples, grid, dur - 70000, dur - 10000) if dur >= 150000 else None
    if _clear(last):
        out["off_end"] = round(last["at"](last["last"]), 1)
    else:  # sin ventana final: la tendencia dentro de la primera también delata un BPM mal
        out["off_end"] = round(first["at"](first["last"]), 1)
    return out


def calibration(measures):
    """Desfase propio del decodificador (sobre todo en MP3) por tipo de archivo: la mediana de lo medido.
    Una grilla mal puesta es la excepción, así que la mediana de muchas canciones es el «cero» real."""
    by = defaultdict(list)
    for ext, m in measures:
        if m and "off" in m:
            by[ext].append(m["off"])
    return {ext: round(statistics.median(v), 1) for ext, v in by.items() if len(v) >= 5}


def audio_reasons(m, ext, calib):
    """Motivos a partir de una medición (con el «cero» del decodificador ya restado)."""
    why = []
    if not m or m.get("err") or m.get("unclear"):
        return why
    if m.get("offbeat"):
        return [{"c": "offbeat", "s": SEV["offbeat"],
                 "t": "Medido: la grilla está en el contratiempo (los kicks caen entre los tiempos)"}]
    zero = calib.get(ext)
    need = SHIFT_MS if zero is not None else 35  # sin calibrar (pocas medidas de ese tipo): solo lo evidente
    off = m["off"] - (zero or 0)
    if abs(off) >= need:
        why.append({"c": "shift", "s": SEV["shift"],
                    "t": f"Medido: el kick cae {abs(off):.0f} ms {'después' if off > 0 else 'antes'} de la grilla"})
    if "off_end" in m and abs(m["off_end"] - m["off"]) >= SHIFT_MS:
        d = m["off_end"] - m["off"]
        why.append({"c": "drift", "s": SEV["drift"],
                    "t": f"Medido: al final la grilla se corre {abs(d):.0f} ms: el BPM no es exacto"})
    if m.get("kick_beat") and m["kick_beat"] != 1:
        s = int(m["kick_ms"] // 1000)
        why.append({"c": "down", "s": SEV["down"],
                    "t": f"Medido: el primer kick ({s // 60}:{s % 60:02d}) cae en el tiempo {m['kick_beat']} del "
                         "compás, no en el 1"})
    return why
