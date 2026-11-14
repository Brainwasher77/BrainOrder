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


# 1) Spotify acepta posiciones en /items: sale solo esa
sp = Fake([T("a"), L1, T("b"), L2], {"items:positions"})
r = sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert r["removed"] == 1 and not r["left"] and sp.uris == [T("a"), T("b"), L2], (r, sp.uris)
print("posiciones:", sp.calls)

# 2) el local está DOS veces y quitas la segunda: sale solo esa (nth=1), la primera se queda
sp = Fake([L1, T("a"), L1, T("b")], {"items:positions"})
r = sp.remove_local("p", [{"uri": L1, "nth": 1}])
assert sp.uris == [L1, T("a"), T("b")] and r["removed"] == 1, sp.uris

# 3) solo acepta la forma vieja (/tracks con uri + posiciones): se prueba hasta dar con ella
sp = Fake([T("a"), L1, L2], {"tracks:uri+pos"})
r = sp.remove_local("p", [{"uri": L1, "nth": 0}, {"uri": L2, "nth": 0}])
assert sp.uris == [T("a")] and r["removed"] == 2, (sp.calls, sp.uris)
print("forma vieja:", sp.calls)

# 4) solo por uri: sirve si no tiene que quedar ninguna aparición...
sp = Fake([T("a"), L1], {"items:uri"})
r = sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert sp.uris == [T("a")] and r["removed"] == 1
# ...pero si está dos veces y quitas una, por uri se irían las dos: no se usa y queda a mano
sp = Fake([L1, L1], {"items:uri"})
r = sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert sp.uris == [L1, L1] and r["removed"] == 0 and r["left"] == [{"uri": L1, "nth": 0}]
assert "items:uri" not in sp.calls

# 5) Spotify no acepta nada: queda a mano, nada se toca
sp = Fake([L1, T("a")], set())
r = sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert r["removed"] == 0 and len(r["left"]) == 1 and sp.uris == [L1, T("a")]
print("nada:", sp.calls)

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

# 7) la forma que funcionó se prueba primero la próxima vez (menos consultas a Spotify)
spotify_api._LOCAL_FORM = None
sp = Fake([L1, T("a")], {"tracks:uri+pos"}); sp.remove_local("p", [{"uri": L1, "nth": 0}])
sp = Fake([L1, T("a")], {"tracks:uri+pos"}); sp.remove_local("p", [{"uri": L1, "nth": 0}])
assert sp.calls == ["tracks:uri+pos"] and sp.uris == [T("a")], sp.calls
print("OK memoria")
