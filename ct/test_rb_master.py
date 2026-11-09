"""Rekordbox manda: cruce de 3 vías al Organizar (no se pisa el orden ni lo que hiciste en Rekordbox) y
cambios hechos en Rekordbox que pasan solos a BrainOrder (Spotify por la cola, carpetas por su memoria)."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP / "support"
config.SUPPORT_DIR.mkdir()
config.save = lambda c: None
import app  # noqa: E402
import rb_cambios  # noqa: E402
import rekordbox_sync as RS  # noqa: E402
from fuentes import carpetas as FC  # noqa: E402

rb_cambios.BASELINE = config.SUPPORT_DIR / "rb_baseline.json"


# ---------------------------------------------------------------- 1) merge_plan
def mp(cur, des, prev):
    r = RS.merge_plan(cur, des, prev)
    return r["final"]


# nada cambió (aunque el orden de Spotify sea otro): Rekordbox se queda con SU orden
assert mp(["/m/c", "/m/a", "/m/b"], ["/m/a", "/m/b", "/m/c"], ["/m/a", "/m/b", "/m/c"]) == ["/m/c", "/m/a", "/m/b"]
# Spotify agregó d: entra al final, sin tocar el orden
assert mp(["/m/c", "/m/a", "/m/b"], ["/m/a", "/m/b", "/m/c", "/m/d"], ["/m/a", "/m/b", "/m/c"]) == ["/m/c", "/m/a", "/m/b", "/m/d"]
# Spotify quitó a: sale
assert mp(["/m/c", "/m/a", "/m/b"], ["/m/b", "/m/c"], ["/m/a", "/m/b", "/m/c"]) == ["/m/c", "/m/b"]
# tú agregaste x en Rekordbox (Spotify aún no la tiene): se queda
assert mp(["/m/a", "/m/x", "/m/b"], ["/m/a", "/m/b"], ["/m/a", "/m/b"]) == ["/m/a", "/m/x", "/m/b"]
# tú quitaste b en Rekordbox (Spotify aún la tiene): no vuelve a entrar
assert mp(["/m/a"], ["/m/a", "/m/b"], ["/m/a", "/m/b"]) == ["/m/a"]
# rutas con «//» (Rekordbox a veces las guarda así) cuentan como la misma
assert mp(["//m/a"], ["/m/a"], ["/m/a"]) == ["//m/a"]
print("merge_plan ok")


# ---------------------------------------------------------------- 2) sync con una base de Rekordbox falsa
class Q(list):
    def first(self):
        return self[0] if self else None


class Content:
    def __init__(self, i, path):
        self.ID, self.FolderPath = i, path


class Song:
    def __init__(self, c, n):
        self.Content, self.TrackNo = c, n


class PL:
    def __init__(self, i, name, parent, attr):
        self.ID, self.Name, self.ParentID, self.Attribute, self.Songs = i, name, parent, attr, []


class FakeDB:
    def __init__(self, *a, **k):
        self.pls, self.contents, self.n = DB_STATE["pls"], DB_STATE["contents"], 100

    def get_playlist(self, ID=None, ParentID=None, Name=None):
        if ID is not None:
            return next((p for p in self.pls if str(p.ID) == str(ID)), None)
        if ParentID is None and Name is None:
            return Q(self.pls)  # como pyrekordbox: sin filtros, todas
        return Q([p for p in self.pls if p.ParentID == ParentID and p.Name == Name])

    def create_playlist_folder(self, name):
        p = PL(str(len(self.pls) + 1), name, "root", 1)
        self.pls.append(p)
        return p

    def create_playlist(self, name, parent=None):
        p = PL(str(len(self.pls) + 1), name, parent.ID if parent else "root", 0)
        self.pls.append(p)
        return p

    def get_content(self, FolderPath=None, **k):
        return Q([c for c in self.contents if c.FolderPath == FolderPath])

    def add_content(self, path, **k):
        self.n += 1
        c = Content(str(self.n), path)
        self.contents.append(c)
        return c

    def query(self, *a):
        class _Q(list):
            def filter(self, *a):
                return self
        return _Q()

    def get_artist(self, Name=None):
        return Q([type("Ar", (), {"ID": 1})()])

    def add_to_playlist(self, pl, c):
        pl.Songs.append(Song(c, len(pl.Songs) + 1))

    def remove_from_playlist(self, pl, s):
        pl.Songs.remove(s)
        for i, x in enumerate(sorted(pl.Songs, key=lambda s: s.TrackNo), 1):
            x.TrackNo = i

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


import pyrekordbox  # noqa: E402

pyrekordbox.MasterDatabase = FakeDB
RS.backup = lambda: Path("/tmp/x.db")
RS.rekordbox_running = lambda: False
folder = PL("1", "BrainOrder", "root", 1)
rbpl = PL("2", "Techno", "1", 0)
cs = {k: Content(str(i), f"/m/{k}.mp3") for i, k in enumerate("abcx", 10)}
for n, k in enumerate(["c", "x", "a"], 1):  # en Rekordbox: tu orden + «x» que agregaste ahí
    rbpl.Songs.append(Song(cs[k], n))
DB_STATE = {"pls": [folder, rbpl], "contents": list(cs.values())}
tr = lambda k: {"status": "ok", "source": f"/m/{k}.mp3", "name": k, "artists": ["z"]}  # noqa: E731
analysis = [{"id": "sp1", "name": "Techno", "tracks": [tr("a"), tr("b"), tr("d")]}]  # Spotify: quitó c, agregó d; b ya estaba
base = {"2": {"pid": "sp1", "name": "Techno", "paths": ["/m/a.mp3", "/m/b.mp3", "/m/c.mp3"]}}  # b la quitaste tú
cfg = {"rekordbox_folder": "BrainOrder", "_rb_base": base}
st = RS.sync(analysis, cfg)
got = [s.Content.FolderPath for s in sorted(rbpl.Songs, key=lambda s: s.TrackNo)]
print("Rekordbox después de Organizar:", got)
assert got == ["/m/x.mp3", "/m/a.mp3", "/m/d.mp3"], got  # c sale (Spotify), x se queda, b no vuelve, d al final
assert [os.path.basename(p) for p in st["baseline"]["2"]["paths"]] == ["x.mp3", "a.mp3", "d.mp3"]
# con «Rekordbox manda» apagado vuelve lo de antes (manda la plataforma)
st = RS.sync(analysis, {**cfg, "rb_master": False})
assert [s.Content.FolderPath for s in sorted(rbpl.Songs, key=lambda s: s.TrackNo)] == ["/m/a.mp3", "/m/b.mp3", "/m/d.mp3"]
print("sync ok")


# ---------------------------------------------------------------- 3) cambios en Rekordbox -> BrainOrder
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "_rb_auto")][0]
root = TMP / "music"
fA, fB = root / "Folk", root / "Cumbia"
fA.mkdir(parents=True)
fB.mkdir(parents=True)
f1 = fA / "Uno - Song.mp3"
f1.write_bytes(b"1")
f2 = fA / "Dos - Song.mp3"
f2.write_bytes(b"2")
pidA, pidB = FC.pid_for(fA), FC.pid_for(fB)
sid = "a" * 22
ana = [
    {"id": "sp1", "name": "Techno", "source": "spotify", "folder": str(root / "Techno"),
     "tracks": [{"id": sid, "source": "/m/a.mp3", "status": "ok"}, {"id": "b" * 22, "source": "/m/b.mp3", "status": "ok"}]},
    {"id": pidA, "name": "Folk", "source": "carpetas", "folder": str(fA),
     "tracks": [{"id": "dir:1", "source": str(f1), "status": "ok"}, {"id": "dir:2", "source": str(f2), "status": "ok"}]},
    {"id": pidB, "name": "Cumbia", "source": "carpetas", "folder": str(fB), "tracks": []},
    {"id": "dz:9", "name": "Deezer", "source": "deezer", "folder": str(root / "Deezer"), "tracks": []},
]
o = A.__new__(A)
o._cfg = {"dest_root": str(root), "folder_playlists": [{"name": "Folk", "path": str(fA)}, {"name": "Cumbia", "path": str(fB)}]}
o._analysis = lambda: ana
o._is_foreign = lambda pid: False
o._build_analysis = lambda light=True: ana
o._noplaylist_dirs = lambda: []
jobs = []
o._spotify_do = lambda j: (jobs.append(j), {"state": "ok"})[1]
o._update_sp = lambda f: None
o._sp_drop = lambda *a: None
import threading  # noqa: E402

o._files = threading.Lock()
state = {"r1": {"name": "Techno", "paths": ["/m/b.mp3", "/m/n.mp3"]},
         "r2": {"name": "Folk", "paths": [str(f2)]},
         "r3": {"name": "Cumbia", "paths": [str(f1)]},
         "r4": {"name": "Deezer", "paths": ["/m/q.mp3"]}}
rb_cambios.save_baseline({"r1": {"pid": "sp1", "name": "Techno", "paths": ["/m/a.mp3", "/m/b.mp3"]},
                          "r2": {"pid": pidA, "name": "Folk", "paths": [str(f1), str(f2)]},
                          "r3": {"pid": pidB, "name": "Cumbia", "paths": []},
                          "r4": {"pid": "dz:9", "name": "Deezer", "paths": []}})
o._rb_changes = lambda: (rb_cambios.diff(rb_cambios.load_baseline(), state, ana), state)
res = o._rb_auto()
print("auto:", res)
kinds = sorted((j["kind"], j["pid"]) for j in jobs)
assert kinds == [("merge_add", "sp1"), ("remove", "sp1")], kinds
assert next(j for j in jobs if j["kind"] == "remove")["uris"] == ["spotify:track:" + sid]
assert next(j for j in jobs if j["kind"] == "merge_add")["paths"] == ["/m/n.mp3"]
# «Uno» la moviste de Folk a Cumbia: Cumbia la recuerda, Folk la olvida y su archivo se muda a Cumbia
assert str(f1) in FC.members(pidB) and str(f1) not in FC.members(pidA)
assert o._cfg["rb_moves"] == [{"src": str(f1), "dest": str(fB), "from": "Folk"}], o._cfg["rb_moves"]
# la foto quedó al día: no hay nada más que preguntar
assert rb_cambios.diff(rb_cambios.load_baseline(), state, ana) == []
assert any("Deezer" in d and "se queda como está" in d for d in res["done"])
# una segunda vuelta no hace nada
jobs.clear()
assert o._rb_auto() is None and not jobs

# quitar muchas de una vez se pregunta (no se hace solo)
ana[0]["tracks"] = [{"id": f"{i:022d}", "source": f"/m/{i}.mp3", "status": "ok"} for i in range(30)]
rb_cambios.save_baseline({"r1": {"pid": "sp1", "name": "Techno", "paths": [f"/m/{i}.mp3" for i in range(30)]}})
state = {"r1": {"name": "Techno", "paths": ["/m/0.mp3"]}}
res = o._rb_auto()
assert not jobs and res["asked"] and rb_cambios.diff(rb_cambios.load_baseline(), state, ana), res

# mudar los archivos (con Rekordbox cerrado) usa la mudanza de siempre (Historial, rutas en programas)
moved = []
app.rekordbox_sync.rekordbox_running = lambda: False
o._relocate_ops = lambda ops, label, extra=None: (moved.extend(ops), {"moved": len(ops), "skipped": []})[1]
o._rb_run_moves()
assert moved == [(str(f1), str(fB))] and o._cfg["rb_moves"] == []
shutil.rmtree(TMP)
print("OK")
