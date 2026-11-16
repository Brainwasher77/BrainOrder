"""Spotify responde 500/502/503/504 (falla de ellos): PUT y DELETE se reintentan solos; POST no (podría
duplicar canciones). Si sigue fallando → SpotifyDown, y lo que se pidió queda en la cola de pendientes en vez de
mostrar el error crudo."""
import os, sys, io, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import spotify_api as S

S.WRITE_WAITS = (0, 0, 0)
S.time.sleep = lambda s: None
S._pace = lambda: None
S._check_pause = lambda: None
S.log = lambda m: None


def server(fails, code=502):
    calls = []

    def urlopen(req, timeout=30):
        calls.append(req.get_method())
        if len(calls) <= fails:
            raise urllib.error.HTTPError(req.full_url, code, "Bad Gateway", {},
                                         io.BytesIO(b'{"error":{"status":502,"message":"An unexpected error occurred."}}'))

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return R(b'{"snapshot_id":"nuevo"}')
    urllib.request.urlopen = urlopen
    return calls


sp = S.Spotify.__new__(S.Spotify)
sp._access = lambda: "tok"

# 1) PUT falla dos veces y a la tercera sale: el usuario no ve nada
c = server(2)
assert sp.send("PUT", "/playlists/p/items", {"uris": []}) == {"snapshot_id": "nuevo"} and len(c) == 3, c
# 2) PUT falla siempre: 1 + 3 reintentos y SpotifyDown (no SpotifyError crudo); se marca la espera
S._DOWN["until"] = 0
c = server(99)
try:
    sp.send("PUT", "/playlists/p/items", {"uris": []}); raise SystemExit("debía fallar")
except S.SpotifyDown as e:
    assert len(c) == 4 and "502" in str(e) and S.down_until(), (c, e)
# 3) DELETE también se reintenta
c = server(1)
sp.send("DELETE", "/playlists/p/items", {"items": []}); assert len(c) == 2, c
# 4) POST (agregar) NO se reintenta: podría duplicar
c = server(1)
try:
    sp.send("POST", "/playlists/p/items", {"uris": ["x"]}); raise SystemExit("debía fallar")
except S.SpotifyDown:
    assert len(c) == 1, c
# 5) leer: _urlopen reintenta y al final SpotifyDown
c = server(99, 503)
try:
    sp.get("/me"); raise SystemExit("debía fallar")
except S.SpotifyDown:
    assert len(c) == 3, c
# 6) un 400 sigue siendo error normal (no se reintenta, no es SpotifyDown)
c = server(1, 400)
try:
    sp.send("PUT", "/playlists/p/items", {}); raise SystemExit("debía fallar")
except S.SpotifyDown:
    raise SystemExit("400 no es falla de Spotify")
except S.SpotifyError:
    assert len(c) == 1
print("spotify_api 5xx: ok")

# 7) _spotify_do: si Spotify falla, el trabajo queda en la cola (con fresh) y no sale error
import app, cola_spotify, config
config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, '_spotify_do')][0]
o = A.__new__(A)
o._sp = lambda: None
Q = []
cola_spotify.add = lambda j: Q.append(j)
app.spotify_api.paused_until = lambda: None


def boom(job, sp):
    raise S.SpotifyDown("Spotify está fallando por su lado ahora mismo (error 502)")
o._spotify_exec = boom
r = o._spotify_do({"kind": "replace", "pid": "p", "name": "X", "uris": ["spotify:track:a"]})
assert r["state"] == "queued" and r["why"] == "down" and Q and Q[0]["fresh"] and Q[0]["kind"] == "replace", (r, Q)

# 8) la cola automática no vuelve a golpear a Spotify mientras está fallando
cola_spotify.load = lambda: [Q[0]]
S._DOWN["until"] = time.time() + 60
assert o.spotify_queue_run(auto=True).get("idle")
print("cola ante 5xx: ok")
