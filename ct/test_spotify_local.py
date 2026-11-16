"""Quitar archivos locales de Spotify (spotify:local:…) desde BrainOrder: Spotify no los quita por uri como a las
demás; se quitan por posición + snapshot y se comprueba releyendo. Si ninguna forma funciona, quedan para
quitarlas a mano (y se dice cuáles)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import spotify_api
from spotify_api import Spotify, SpotifyError

L1 = "spotify:local:Ancient+Methods:Turn+Ice:Knives:301"
L2 = "spotify:local:Rebekah:Fear:Ghost+Process:380"
T = lambda c: "spotify:track:" + c * 22


class Fake(Spotify):
    """Playlist en memoria; `accept` = qué formas de DELETE acepta este «Spotify»."""
    def __init__(self, uris, accept):
        self.uris, self.accept, self.snap, self.calls = list(uris), accept, 1, []

    def get(self, path, params=None, _retry=3):
        if params and params.get("fields") == "snapshot_id":
            return {"snapshot_id": f"s{self.snap}"}
        return {"items": [{"item": {"uri": u}} for u in self.uris], "next": None, "total": len(self.uris)}

    def send(self, method, path, body=None, _retry=3):
        form = path.rsplit("/", 1)[-1] + ":" + ("positions" if "positions" in body else
                                                 "uri+pos" if any("positions" in x for x in body.get("items") or body.get("tracks") or []) else "uri")
        self.calls.append(form)
        if form not in self.accept:
            raise SpotifyError(f"Error 400 ({form})")
        if form.endswith("uri"):
            gone = {x["uri"] for x in body["items"]}
            self.uris = [u for u in self.uris if u not in gone]
        else:
            assert body["snapshot_id"] == f"s{self.snap}", "sin snapshot vigente no se quita por posición"
            pos = body.get("positions") or [p for x in body.get("items") or body.get("tracks") for p in x["positions"]]
            self.uris = [u for i, u in enumerate(self.uris) if i not in set(pos)]
        self.snap += 1
        return {"snapshot_id": f"s{self.snap}"}


# 1) (2.57.9) la que no tiene que quedar sale por uri, la única forma que Spotify tiene desde feb 2026
spotify_api._POS_DEAD["v"] = False
sp = Fake([T("a"), L1, T("b"), L2], {"items:uri"})
r = sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert r["removed"] == 1 and not r["left"] and sp.uris == [T("a"), T("b"), L2], (r, sp.uris)
assert sp.calls == ["items:uri"], sp.calls

# 2) repetida (debe quedar una): por posición, si Spotify lo acepta
sp = Fake([L1, T("a"), L1, T("b")], {"items:positions"})
r = sp.remove_local("p", [{"uri": L1, "nth": 1}])
assert sp.uris == [L1, T("a"), T("b")] and r["removed"] == 1, sp.uris
assert "items:uri" not in sp.calls  # por uri se irían las dos

# 3) el caso de Frank (Industrial Techno): 9 locales que salen del todo + «Alter Ego» dos veces, y Spotify
#    ya no acepta posiciones -> salen las 9, Alter Ego queda para quitarla a mano (una sola, no las 10)
AE = "spotify:local:X:Y:Alter+Ego:300"
nine = [f"spotify:local:A:B:T{i}:200" for i in range(9)]
sp = Fake(nine + [T("a"), AE, AE], {"items:uri"})
r = sp.remove_local("p", [{"uri": u, "nth": 0} for u in nine] + [{"uri": AE, "nth": 1}])
assert sp.uris == [T("a"), AE, AE] and r["removed"] == 9 and r["left"] == [{"uri": AE, "nth": 1}], (sp.uris, r)
assert spotify_api._POS_DEAD["v"]
calls = len(sp.calls)
# 4) ya se sabe que no acepta posiciones: no se vuelve a gastar en probarlas
sp = Fake([AE, AE], {"items:uri"})
r = sp.remove_local("p", [{"uri": AE, "nth": 1}])
assert sp.calls == [] and r["left"], sp.calls
spotify_api._POS_DEAD["v"] = False

# 5) Spotify no acepta nada: queda a mano, nada se toca
sp = Fake([L1, T("a")], set())
r = sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert r["removed"] == 0 and len(r["left"]) == 1 and sp.uris == [L1, T("a")]
print("locales:", sp.calls)

# 6) en BrainOrder: quitar una fila local arma el trabajo «remove» con local y el aviso trae el nombre
import app, config
config.save = lambda c: None
config.log = lambda m: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'playlist_tracks_move')][0]
rows = [{"pos": 0, "id": "a" * 22, "name": "Uno", "source": None},
        {"pos": 1, "id": "local:" + L1, "name": "Knives", "source": None},
        {"pos": 2, "id": "local:" + L1, "name": "Knives", "source": None}]
PL = {"pa": {"id": "pa", "name": "Industrial", "tracks": rows}}
cache = {"playlists": [{"id": "pa", "tracks": [{"id": r["id"]} for r in rows]}], "foreign_ok": []}
for accept, done, manual in (({"items:positions"}, 1, 0), (set(), 0, 1)):
    spotify_api._POS_DEAD["v"] = False
    o = A.__new__(A); o._cfg = {"dest_root": "/tmp/nada"}
    o._analysis = lambda: list(PL.values())
    o._pl_ctx = lambda pid, an=None: (PL[pid], 'spotify', None, None)
    o._is_foreign = lambda pid: False
    o._set_stage = lambda *a: None
    o._task = lambda fn, k, l, files=False: fn()
    o._load_sp = lambda: json.loads(json.dumps(cache))
    o._update_sp = lambda f: f(cache)
    o._build_analysis = lambda light=True: list(PL.values())
    o._relocate_ops = lambda ops, label, extra=None: {"moved": 0, "changes": {}}
    fake = Fake([T("a"), L1, L1], accept)
    o._sp = lambda: fake
    o._spotify_ready = lambda: fake
    spotify_api.paused_until = lambda: None
    r = o.playlist_tracks_move('pa', [2], None)["result"]
    assert r.get("local_done", 0) == done and r["no_uri"] == manual, r
    if manual:
        assert r["manual"] == ["Ancient Methods - Knives"], r
        assert fake.uris == [T("a"), L1, L1]
    else:
        assert fake.uris == [T("a"), L1], fake.uris
    print("app:", {k: r.get(k) for k in ("local_done", "no_uri", "manual")})
print("OK")

