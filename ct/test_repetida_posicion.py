"""2.57.7: quitar UNA copia de una canción repetida.
- Spotify con archivos locales o canciones que esperan: ya no da error; sale por su posición o, si Spotify no
  lo acepta, se quita y se vuelve a poner en su sitio (nunca se pierde: lo que no alcanzó a volver queda para agregar).
- Playlist de carpeta con el mismo archivo dos veces (archivo + recuerdo): se olvida el recuerdo."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import spotify_api as S
from spotify_api import Spotify, SpotifyError
S.log = lambda m: None
T = lambda c: "spotify:track:" + c * 22
L = "spotify:local:A:B:C:200"


class Fake(Spotify):
    """Playlist en memoria que NO acepta quitar por posición (como el Spotify de hoy), sí por uri y agregar en posición."""
    def __init__(self, uris, fail_add_after=None):
        self.uris, self.snap, self.adds, self.fail = list(uris), 1, 0, fail_add_after

    def get(self, path, params=None, _retry=3):
        if params and params.get("fields") == "snapshot_id":
            return {"snapshot_id": f"s{self.snap}"}
        return {"items": [{"item": {"uri": u}} for u in self.uris], "next": None, "total": len(self.uris)}

    def send(self, method, path, body=None, _retry=3):
        if method == "DELETE":
            if "positions" in body or any("positions" in x for x in body.get("items") or body.get("tracks") or []):
                raise SpotifyError("Error 400 positions")
            gone = {x["uri"] for x in body["items"]}
            self.uris = [u for u in self.uris if u not in gone]
        elif method == "POST":
            if self.fail is not None and self.adds >= self.fail:
                raise S.SpotifyDown("Error 502")
            self.adds += 1
            p = body.get("position", len(self.uris))
            self.uris[p:p] = body["uris"]
        self.snap += 1
        return {"snapshot_id": f"s{self.snap}"}


S._POS_DEAD["v"] = False
# 1) a, b, a(2ª), L, c, a(3ª): quitar la 2ª «a» -> a, b, L, c, a
sp = Fake([T("a"), T("b"), T("a"), L, T("c"), T("a")])
r = sp.remove_nth("p", [{"uri": T("a"), "nth": 1}])
assert sp.uris == [T("a"), T("b"), L, T("c"), T("a")] and r["removed"] == 1 and not r["left"] and not r["restore"], (sp.uris, r)
assert S._POS_DEAD["v"]  # ya no vuelve a probar por posición
# 2) dos canciones repetidas a la vez, quitando la PRIMERA aparición de una
sp = Fake([T("x"), T("a"), T("b"), T("x"), T("b"), L])
r = sp.remove_nth("p", [{"uri": T("x"), "nth": 0}, {"uri": T("b"), "nth": 1}])
assert sp.uris == [T("a"), T("b"), T("x"), L], sp.uris
# 3) nunca quita la última copia, aunque se lo pidan dos veces
sp = Fake([T("a"), T("a")])
r = sp.remove_nth("p", [{"uri": T("a"), "nth": 0}, {"uri": T("a"), "nth": 1}])
assert sp.uris == [T("a")], sp.uris
# 4) se corta al volver a ponerla: lo que falta vuelve en «restore»
sp = Fake([T("a"), T("b"), T("a")], fail_add_after=0)
r = sp.remove_nth("p", [{"uri": T("a"), "nth": 1}])
assert sp.uris == [T("b")] and r["restore"] == [T("a")], (sp.uris, r)
print("remove_nth: ok")

# 5) playlist_tracks_move con un archivo local en la playlist: ya no da error, pide «remove_nth»
import app, config
config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'playlist_tracks_move')][0]
SP = lambda c: c * 22
PL = {"id": "pa", "name": "Salseame", "tracks": [{"pos": 0, "id": SP('a'), "name": "Uno", "artists": ["X"]},
      {"pos": 1, "id": "local:" + L, "name": "Local"}, {"pos": 2, "id": SP('b'), "name": "Dos"},
      {"pos": 3, "id": SP('a'), "name": "Uno", "artists": ["X"]}, {"pos": 4, "id": SP('c'), "name": "Tres"},
      {"pos": 5, "id": SP('c'), "name": "Tres (álbum)"}]}
CACHE = {"playlists": [{"id": "pa", "tracks": [{"id": t["id"]} for t in PL["tracks"]], "snapshot": "x", "analyzed_snapshot": "x"}]}
o = A.__new__(A); o._cfg = {"dest_root": tempfile.mkdtemp()}
o._analysis = lambda: [PL]
o._pl_ctx = lambda pid, an=None: (PL, 'spotify', None, None)
o._pl_can_remove = lambda *a: True
o._is_foreign = lambda pid: False
o._spotify_ready = lambda: object()
o._set_stage = lambda *a: None
o._task = lambda fn, k, l, files=False: fn()
o._load_sp = lambda: CACHE
o._update_sp = lambda f: f(CACHE)
o._build_analysis = lambda light=True: [PL]
o._rb_ref = lambda *a, **k: None
o._rb_ready = lambda *a: None
o._relocate_ops = lambda ops, label, extra=None: {"moved": 0, "changes": {}}
o.jobs = []
o._spotify_do = lambda j: (o.jobs.append(j), {"state": "ok", "left": []})[1]
app.spotify_api.paused_until = lambda: None
r = o.playlist_tracks_move('pa', [3, 5], None)
kinds = {j["kind"]: j for j in o.jobs}
assert kinds["remove_nth"]["items"] == [{"uri": "spotify:track:" + SP('a'), "nth": 1},
                                       {"uri": "spotify:track:" + SP('c'), "nth": 1}], o.jobs
assert "remove" not in kinds and "replace" not in kinds, o.jobs
ids = [t["id"] for t in CACHE["playlists"][0]["tracks"]]
assert ids == [SP('a'), "local:" + L, SP('b'), SP('c')], ids
print("Spotify con locales: ok", [j["kind"] for j in o.jobs])

# 6) carpeta: el mismo archivo dos veces (archivo + recuerdo con otro nombre): se olvida el recuerdo
from fuentes import carpetas as FC
root = Path(tempfile.mkdtemp())
real = root / "Proyecto Uno - El Tiburon (esta suena mas duro).m4a"; real.write_bytes(b"x")
old = str(root / "viejo" / "Proyecto Uno - El Tiburon.m4a")
FC.members = lambda pid: [str(real), old]
rows_all = [{"pos": 0, "id": FC.track_id(str(real)), "source": str(real)},
            {"pos": 1, "id": FC.track_id(old), "source": str(real)}]
nk = lambda x: os.path.normcase(os.path.normpath(x))
for leave in (0, 1):  # sea cual sea la que marcaste
    rows = [rows_all[leave]]
    stay = {nk(r["source"]) for r in rows_all if r["pos"] != leave}
    got = A._fc_shared_memories("p", rows, rows_all, stay)
    assert got == [old], (leave, got)
print("carpeta con recuerdo: ok")

# 7) el archivo de verdad vive en la carpeta pero no está en la memoria: igual se olvida el recuerdo
FC.members = lambda pid: [old]
rows = [rows_all[0]]
stay = {nk(rows_all[1]["source"])}
assert A._fc_shared_memories("p", rows, rows_all, stay, str(root)) == [old]
assert A._fc_shared_memories("p", rows, rows_all, stay) == []  # sin saber la carpeta no se arriesga
print("carpeta sin memoria del archivo: ok")
