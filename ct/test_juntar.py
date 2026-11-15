"""2.50.0: juntar la música de tus otras carpetas en tu carpeta de playlists."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP / "sup"
config.SUPPORT_DIR.mkdir()
config.save = lambda c: None
import app  # noqa: E402
import juntar  # noqa: E402

M = TMP / "Music"
BL, PR, DJ = M / "BRAIN LIBRARY", M / "Playlists rekordbox", M / "DJ Library"


def w(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


# tu carpeta de playlists (con subcarpetas como en Rekordbox)
w(BL / "Crossover" / "ADC" / "Rumba ADC" / "Chipi.m4a", b"otra")        # mismo nombre, otra duración: igual es repetida
w(BL / "Brainwasher" / "Soft" / "Jungle House" / "Ferrari.mp3", b"igual")  # misma grabación
w(BL / "Pop" / "Latch.mp3", b"pop")
# afuera, con subcarpetas
a = w(PR / "Crossover" / "MGNO" / "Electronica-Dance" / "Tema A.mp3")
b = w(PR / "Desembale" / "Chipi.m4a", b"mia")
c = w(PR / "Brainwasher" / "Soft" / "Ferrari.mp3", b"igual")
d = w(PR / "Desembale" / "Huerfana.mp3")
h = w(PR / "Desembale" / "Latch.mp3".replace("Latch", "Tema A"), b"distinta")  # sin playlist, mismo nombre que una que entra
e = w(PR / "Desembale" / "Latch.mp3", b"pop")                    # sin playlist pero ya está en BRAIN LIBRARY
f = w(DJ / "Merengue" / "Tiburon.aif")
w(PR / "Desembale" / "_duplicados" / "vieja.mp3")                 # lo de _duplicados no se toca
os.symlink(str(PR / "no existe.mp3"), str(PR / "Brainwasher" / "roto.mp3"))  # acceso directo roto
g = w(PR / "Importada" / "Mia.mp3")                               # playlist importada desde esa carpeta

home = lambda *p: str(BL.joinpath(*p))
analysis = [
    {"id": "e", "name": "Electronica-Dance", "tracks": [{"source": a, "dest_dir": home("Electronica-Dance")}]},
    {"id": "r", "name": "Rumba ADC", "tracks": [{"source": b, "dest_dir": home("Crossover", "ADC", "Rumba ADC")}]},
    {"id": "j", "name": "Jungle House", "tracks": [{"source": c, "dest_dir": home("Brainwasher", "Soft", "Jungle House")}]},
    {"id": "m", "name": "Merengue", "tracks": [{"source": f, "dest_dir": home("Merengue")}]},
    {"id": "x", "name": "Ya está", "tracks": [{"source": home("Pop", "Latch.mp3"), "dest_dir": home("Pop")}]},
]
same = lambda x, y: Path(x).read_bytes() == Path(y).read_bytes()
pl = juntar.plan(analysis, [str(PR), str(DJ)], str(BL), str(BL / "_Sin Playlist"), [str(PR / "Importada")], same,
                 lambda n: Path(n).stem.lower())
ops = {o[0]: (o[1], o[2]) for o in pl["ops"]}
assert ops[a] == (home("Electronica-Dance"), None), ops[a]
assert ops[b][0] == home("_duplicados", "Rumba ADC") and pl["dup_of"][b] == home("Crossover", "ADC", "Rumba ADC", "Chipi.m4a"), ops[b]
assert ops[c][0] == home("_duplicados", "Jungle House") and pl["dup_of"][c] == home("Brainwasher", "Soft", "Jungle House", "Ferrari.mp3")
assert ops[d] == (home("_Sin Playlist"), None) and ops[f] == (home("Merengue"), None)
assert ops[e][0].startswith(home("_duplicados")) and pl["dup_of"][e] == home("Pop", "Latch.mp3")
assert ops[str(PR / "Desembale" / "_duplicados" / "vieja.mp3")][0] == home("_duplicados", "Playlists rekordbox", "Desembale", "_duplicados")
assert ops[h] == (home("_Sin Playlist"), None), ops[h]  # en BRAIN LIBRARY todavía no hay «Tema A»: no es repetida
assert g not in ops and len(ops) == 8, sorted(ops)
assert pl["by_root"][str(PR)] == {"home": 1, "nopl": 2, "dup": 4, "kept": 1}, pl["by_root"]
print("plan ok")

# ------------------------------------------------ BrainOrder: mueve, anota y deja la carpeta fuera
moves = []


def fake_relocate(ops, cfg, progress=None):
    ch = {}
    for op in ops:
        src, dest = op[0], op[1]
        dst = Path(dest) / (op[2] if len(op) > 2 and op[2] else Path(src).name)
        assert not dst.exists(), dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        ch[src] = str(dst)
    moves.append(ch)
    return {"moved": len(ch), "skipped": [], "changes": ch}


app.organizador.relocate = fake_relocate
app.unificar.rb_paths = lambda progress=None: set()
REC = []
app.historial.record = lambda kind, label, items, extra=None: REC.append((label, items, extra)) or "op1"
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "gather_run")][0]
o = A.__new__(A)
o._cfg = {"dest_root": str(BL), "inbox": str(M / "Nuevas"), "library_roots": [str(PR), str(DJ)],
          "folder_playlists": [{"name": "Importada", "path": str(PR / "Importada")}]}
o._an = analysis
o._analysis = lambda: analysis
o._build_analysis = lambda light=True: analysis
o._progress = lambda *a, **k: None
o._set_stage = lambda *a: None
o._dj_precheck = lambda: None
o._dj_fix = lambda *a, **k: ({}, [])
o._state = app.threading.RLock()
o._files = app.threading.Lock()
o._task = lambda fn, key, label, files=False: {"ok": True, **fn()}
CLEAN = []
o._shortcuts_clean = lambda r: CLEAN.append(r) or {"root_removed": r == str(DJ), "links": 0, "broken": 1}
assert [Path(x).name for x in o._gather_roots()] == ["Playlists rekordbox", "DJ Library"]
r = o.gather_run([str(PR), str(DJ)])
res = r["result"]
assert r["ok"] and res["moved"] == 8 and (res["home"], res["nopl"], res["dup"]) == (2, 2, 4), res
assert (BL / "Electronica-Dance" / "Tema A.mp3").exists() and (BL / "_duplicados" / "Rumba ADC" / "Chipi.m4a").exists()
assert not (BL / "Crossover" / "ADC" / "Rumba ADC" / "Chipi (2).m4a").exists()
assert (BL / "Crossover" / "ADC" / "Rumba ADC" / "Chipi.m4a").read_bytes() == b"otra"  # no se pisó
assert (BL / "Merengue" / "Tiburon.aif").exists() and (BL / "_Sin Playlist" / "Huerfana.mp3").exists()
assert (PR / "Importada" / "Mia.mp3").exists()
# las carpetas que quedaron solas se borran (la de la playlist importada se queda)
assert not (PR / "Desembale").exists() and not (PR / "Crossover").exists() and not (PR / "Brainwasher" / "Soft").exists(), \
    sorted(str(x) for x in PR.rglob("*"))
label, items, extra = REC[0]
assert "Playlists rekordbox" in label and len(items) == 8 and len(extra["dup_of"]) == 3, REC
assert CLEAN == [str(PR), str(DJ)] and not DJ.exists() or not any(DJ.rglob("*.aif")), list(DJ.rglob("*"))
print("juntar ok")
print("OK")
