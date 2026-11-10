"""Endurecimiento: la sesión de Spotify solo viaja a api.spotify.com, el inicio de sesión solo escucha en
este computador, los links cortos de Deezer solo se abren si son de Deezer, y la vista previa de audio solo
entrega audio de tus carpetas a quien tiene la clave."""
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
config.LOG_FILE = TMP / "brainorder.log"
import spotify_api as S  # noqa: E402

S.TOKEN_FILE = TMP / "token.json"
S.PAUSE_FILE = TMP / "pausa.json"
sp = S.Spotify("a" * 32, "http://127.0.0.1:8888/callback")
sp.token = {"access_token": "SECRETO", "refresh_token": "r", "expires_at": 9e12}
sent = []
S._urlopen = lambda req, timeout=30, tries=3: sent.append(req.full_url) or (_ for _ in ()).throw(S.SpotifyNetError("x"))
for url in ("http://api.spotify.com/v1/me", "https://evil.example/v1/me", "https://api.spotify.com.evil.example/x",
            "https://evil.example/?https://api.spotify.com"):
    try:
        sp.get(url)
        raise SystemExit(f"mandó la sesión a {url}")
    except S.SpotifyNetError:
        raise SystemExit(f"mandó la sesión a {url}")
    except S.SpotifyError:
        pass
assert not sent, sent
try:
    sp.get("/me", _retry=0)
except S.SpotifyNetError:
    pass
assert sent == ["https://api.spotify.com/v1/me"], sent

# el inicio de sesión no abre un puerto hacia la red
import webbrowser  # noqa: E402

webbrowser.open = lambda *a, **k: True
try:
    S.Spotify("a" * 32, "http://0.0.0.0:8888/callback").login(timeout=1)
    raise SystemExit("escuchó en toda la red")
except S.SpotifyError as e:
    assert "Redirect URI" in str(e)

# links cortos de Deezer
from fuentes import deezer_src as D  # noqa: E402

opened = []
_real = urllib.request.urlopen
D.urllib.request.urlopen = lambda req, timeout=15: opened.append(req.full_url) or (_ for _ in ()).throw(OSError("sin red"))
for t in ("file:///etc/passwd#link.deezer.com", "http://evil.example/link.deezer.com/x", "https://evil.example/?deezer.page.link"):
    assert D._resolve(t) == (None, None), t
assert not opened, opened
D._resolve("https://link.deezer.com/s/abc")
assert opened == ["https://link.deezer.com/s/abc"], opened
assert D._resolve("https://www.deezer.com/es/playlist/123") == ("playlist", "123")
assert D._resolve("5551234") == ("user", "5551234")
urllib.request.urlopen = _real

# vista previa
import audio_server as A  # noqa: E402

music = TMP / "musica"
music.mkdir()
(music / "a.mp3").write_bytes(b"ID3" + b"0" * 5000)
(music / "nota.txt").write_text("x")
(TMP / "fuera.mp3").write_bytes(b"ID3")
port = A.start(lambda: [str(music)])


def code(url, **h):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=5) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, b"", e.headers


ok = A.url_for(music / "a.mp3")
st, body, hd = code(ok)
assert st == 200 and len(body) == 5003 and hd.get("Access-Control-Allow-Origin") is None, (st, len(body))
st, body, _ = code(ok, Range="bytes=0-9")
assert st == 206 and len(body) == 10
assert code(ok.replace("k=" + A._STATE["key"], "k=mala"))[0] == 403
assert code(A.url_for(TMP / "fuera.mp3"))[0] == 404
assert code(A.url_for(music / "nota.txt"))[0] == 404
assert code(A.url_for(music / ".." / "fuera.mp3"))[0] == 404
assert code(ok, Host="evil.example")[0] == 403
print("OK")
