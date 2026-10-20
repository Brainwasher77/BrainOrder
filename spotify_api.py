"""Cliente mínimo de la Web API de Spotify (PKCE, solo librería estándar).

Compatible con las reglas de Development Mode de 2026:
  - /playlists/{id}/items  (antes /tracks), campo item (antes track)
  - solo se leen playlists propias o colaborativas
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import TOKEN_FILE, log

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
# Lectura + modificar tus playlists (para pasar a Spotify los cambios que hagas en Rekordbox)
SCOPES = ("playlist-read-private playlist-read-collaborative user-library-read "
          "playlist-modify-public playlist-modify-private user-library-modify")
WRITE_SCOPES = {"playlist-modify-public", "playlist-modify-private"}


class SpotifyError(Exception):
    pass


class SpotifyPaused(SpotifyError):
    """Spotify castigó a la app por exceso de consultas: no se le pregunta nada hasta que pase."""


# ---------- pausa por exceso de consultas (se recuerda aunque cierres la app) ----------
PAUSE_FILE = TOKEN_FILE.with_name("spotify_pausa.json")
_PACE = {"t": 0.0, "lock": threading.Lock()}
MIN_GAP = 0.12  # como mucho ~8 consultas por segundo entre todas las tareas


def paused_until():
    """Hora (epoch) hasta la que Spotify pidió no consultar, o None."""
    try:
        until = float(json.loads(PAUSE_FILE.read_text("utf-8")).get("until", 0))
    except Exception:
        return None
    return until if until > time.time() else None


def _hora(epoch):
    return time.strftime("%H:%M", time.localtime(epoch)) + \
        (" de mañana" if time.localtime(epoch).tm_yday != time.localtime().tm_yday else "")


def _pause_error(until):
    mins = max(1, round((until - time.time()) / 60))
    when = f"{mins} min" if mins < 90 else f"{mins // 60} h {mins % 60:02d} min"
    return SpotifyPaused(f"Spotify puso a tu app en pausa por exceso de consultas hasta las {_hora(until)} (faltan {when}). "
                         "Mientras tanto BrainOrder usa lo último que leyó de Spotify; Deezer, archivos y todo lo demás siguen funcionando.")


def _check_pause():
    until = paused_until()
    if until:
        raise _pause_error(until)


def _pace():
    """Separa las consultas (entre todas las tareas a la vez) para no volver a exceder el límite."""
    with _PACE["lock"]:
        wait = MIN_GAP - (time.time() - _PACE["t"])
        if wait > 0:
            time.sleep(wait)
        _PACE["t"] = time.time()


_TOKEN_LOCK = threading.Lock()  # varias tareas a la vez: un solo refresco del token
_NET_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, OSError)


def _urlopen(req, timeout=30, tries=3):
    """urlopen con reintentos ante cortes de red y errores 5xx de Spotify."""
    delay = 1.0
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except _NET_ERRORS as e:
            if attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise SpotifyError(f"No pude conectar con Spotify. Revisa tu conexión a internet. ({e})")


def _retry_after(e):
    try:
        secs = int(e.headers.get("Retry-After", "2"))
    except (TypeError, ValueError):
        secs = 2
    if secs > 30:
        until = time.time() + secs
        try:
            PAUSE_FILE.write_text(json.dumps({"until": until}), "utf-8")
        except OSError:
            pass
        log(f"Spotify: pausa por exceso de consultas ({secs} s, hasta {_hora(until)})")
        raise _pause_error(until)
    time.sleep(secs + 1)


class Spotify:
    def __init__(self, client_id: str, redirect_uri: str):
        self.client_id = client_id.strip()
        self.redirect_uri = redirect_uri
        self.token = self._load_token()
        self.foreign = []

    # ---------- tokens ----------
    def _load_token(self):
        try:
            return json.loads(TOKEN_FILE.read_text("utf-8"))
        except Exception:
            return None

    def _save_token(self, tok):
        tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
        if self.token and "refresh_token" not in tok:
            tok["refresh_token"] = self.token.get("refresh_token")
        if self.token and "scope" not in tok and self.token.get("scope"):
            tok["scope"] = self.token["scope"]
        self.token = tok
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        # atómico y privado: otra tarea que lo lea a la vez nunca ve un archivo a medias
        tmp = TOKEN_FILE.with_name(f".{TOKEN_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(tok))
        os.replace(tmp, TOKEN_FILE)

    def logout(self):
        self.token = None
        try:
            TOKEN_FILE.unlink()
        except FileNotFoundError:
            pass

    @property
    def connected(self):
        return bool(self.token and self.token.get("refresh_token"))

    def _post_token(self, data):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, headers={
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with _urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")
            if "invalid_grant" in detail:
                raise SpotifyError("La sesión de Spotify venció o se revocó. Toca «Conectar Spotify» para volver a entrar.")
            raise SpotifyError(f"Spotify rechazó el token ({e.code}): {detail[:200]}")

    def _refresh(self, stale=None):
        """Renueva el token. Si otra tarea ya lo renovó mientras tanto, se usa ese (Spotify invalida
        el refresh_token viejo al renovar: dos renovaciones a la vez dejaban la sesión rota)."""
        with _TOKEN_LOCK:
            disk = self._load_token()
            if disk and disk.get("access_token") and disk.get("access_token") != (stale or (self.token or {}).get("access_token")) \
                    and time.time() < disk.get("expires_at", 0):
                self.token = disk
                return
            if disk and disk.get("refresh_token"):
                self.token = disk
            if not self.connected:
                raise SpotifyError("No has conectado tu cuenta de Spotify.")
            tok = self._post_token({
                "grant_type": "refresh_token",
                "refresh_token": self.token["refresh_token"],
                "client_id": self.client_id,
            })
            self._save_token(tok)

    def _access(self):
        if not self.connected:
            raise SpotifyError("No has conectado tu cuenta de Spotify.")
        if time.time() >= self.token.get("expires_at", 0):
            self._refresh()
        return self.token["access_token"]

    # ---------- login PKCE ----------
    def login(self, timeout=180):
        if not self.client_id:
            raise SpotifyError("Falta el Client ID de tu app de Spotify (pestaña Ajustes).")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        parsed = urllib.parse.urlparse(self.redirect_uri)
        result = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if urllib.parse.urlparse(self.path).path != parsed.path:
                    self.send_response(404); self.end_headers(); return
                result["code"] = (q.get("code") or [None])[0]
                result["state"] = (q.get("state") or [None])[0]
                result["error"] = (q.get("error") or [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = "Listo, ya puedes volver a BrainOrder." if result["code"] else "No se pudo conectar."
                self.wfile.write(f"<html><body style='font-family:-apple-system;background:#111;color:#eee;"
                                 f"display:grid;place-items:center;height:100vh'><h2>{msg}</h2></body></html>".encode())

            def log_message(self, *a):
                pass

        server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
        server.timeout = 1
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
            "state": state,
        })
        webbrowser.open(url)
        end = time.time() + timeout
        try:
            while time.time() < end and "code" not in result:
                server.handle_request()
        finally:
            server.server_close()
        if result.get("error") or not result.get("code"):
            raise SpotifyError(f"Login cancelado o expirado ({result.get('error') or 'sin respuesta'}).")
        if result.get("state") != state:
            raise SpotifyError("Respuesta de Spotify inválida (state).")
        tok = self._post_token({
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        })
        self._save_token(tok)
        return self.me()

    # ---------- API ----------
    def get(self, path_or_url, params=None, _retry=3):
        url = path_or_url if path_or_url.startswith("http") else API + path_or_url
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        _check_pause()  # en pausa no se consulta: cada consulta extra puede alargar el castigo
        access = self._access()
        _pace()
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
        try:
            with _urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and _retry:
                _retry_after(e)
                return self.get(path_or_url, params, _retry - 1)
            if e.code == 401 and _retry:
                self._refresh(stale=access)
                return self.get(path_or_url, params, _retry - 1)
            raise SpotifyError(f"Error {e.code} en {url.split('?')[0]}: {e.read().decode(errors='ignore')[:200]}")

    def paged(self, path, params, on_page=None):
        data = self.get(path, params)
        seen = 0
        while True:
            items = data.get("items", [])
            seen += len(items)
            if on_page:
                on_page(seen, data.get("total"))
            for it in items:
                yield it
            nxt = data.get("next")
            if not nxt:
                break
            data = self.get(nxt)

    def me(self):
        return self.get("/me")

    # ---------- escribir (Rekordbox -> Spotify) ----------
    @property
    def can_write(self):
        """La sesión guardada tiene permiso para modificar playlists (si no, hay que reconectar)."""
        granted = set(((self.token or {}).get("scope") or "").split())
        return WRITE_SCOPES <= granted

    def send(self, method, path, body=None, _retry=3):
        url = path if path.startswith("http") else API + path
        data = json.dumps(body).encode() if body is not None else None
        _check_pause()
        access = self._access()
        _pace()
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {access}", "Content-Type": "application/json"})
        try:
            # escribir no se reintenta por cortes de red (podría duplicar canciones); sí por 429/401
            with _urlopen(req, timeout=30, tries=1) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 429 and _retry:
                _retry_after(e)
                return self.send(method, path, body, _retry - 1)
            if e.code == 401 and _retry:
                self._refresh(stale=access)
                return self.send(method, path, body, _retry - 1)
            detail = e.read().decode(errors="ignore")[:200]
            if e.code == 403:
                raise SpotifyError("Spotify no dejó modificar (403). Reconecta Spotify para dar permiso de edición; "
                                   f"si sigue, tu app de desarrollador no tiene permiso de escritura. Detalle: {detail}")
            raise SpotifyError(f"Error {e.code} en {method} {url.split('?')[0]}: {detail}")

    def create_playlist(self, name, public=False, description="Creada desde Rekordbox con BrainOrder"):
        return self.send("POST", "/me/playlists", {"name": name, "public": public, "description": description})

    def rename_playlist(self, pid, name):
        return self.send("PUT", f"/playlists/{pid}", {"name": name})

    def add_items(self, pid, uris, position=None):
        for i in range(0, len(uris), 100):
            body = {"uris": uris[i:i + 100]}
            if position is not None:
                body["position"] = position + i
            self.send("POST", f"/playlists/{pid}/items", body)

    def remove_items(self, pid, uris):
        for i in range(0, len(uris), 100):
            self.send("DELETE", f"/playlists/{pid}/items", {"items": [{"uri": u} for u in uris[i:i + 100]]})

    def save_to_library(self, uris):
        for i in range(0, len(uris), 40):
            self.send("PUT", "/me/library", {"uris": uris[i:i + 40]})

    def remove_from_library(self, uris):
        """También sirve para dejar de seguir (borrar de tu biblioteca) una playlist: spotify:playlist:ID."""
        for i in range(0, len(uris), 40):
            self.send("DELETE", "/me/library", {"uris": uris[i:i + 40]})

    def search_track(self, isrc=None, artist="", title=""):
        """-> lista de tracks simplificados (máx. 10, límite de Spotify)."""
        q = f"isrc:{isrc}" if isrc else f'track:"{title}" artist:"{artist}"' if artist else title
        res = self.get("/search", {"q": q, "type": "track", "limit": 10})
        return [t for t in (self._track(x) for x in (res.get("tracks") or {}).get("items") or []) if t]

    @staticmethod
    def _track(raw):
        """Convierte un track de la API a un dict simple; None si no es canción."""
        if not raw or raw.get("type", "track") != "track" or raw.get("is_local") and not raw.get("name"):
            return None
        artists = [a.get("name", "") for a in raw.get("artists", []) if a.get("name")]
        return {
            "id": raw.get("id") or f"local:{raw.get('uri')}",
            "name": raw.get("name", ""),
            "artists": artists,
            "album": (raw.get("album") or {}).get("name", ""),
            "duration_ms": raw.get("duration_ms", 0),
            "url": (raw.get("external_urls") or {}).get("spotify", ""),
            "isrc": ((raw.get("external_ids") or {}).get("isrc") or ""),
        }

    def list_mine(self):
        """Solo la LISTA de tus playlists (sin canciones): rápido.
        Devuelve [{id, name, snapshot, total}] y deja las ajenas en self.foreign."""
        me = self.me()
        my_id = me.get("id")
        pls = [p for p in self.paged("/me/playlists", {"limit": 50}) if p]
        own, self.foreign = [], []
        for p in pls:
            owner = p.get("owner") or {}
            if owner.get("id") == my_id or p.get("collaborative"):
                box = p.get("items") or p.get("tracks") or {}
                own.append({"id": p["id"], "name": p.get("name") or "Sin nombre",
                            "snapshot": p.get("snapshot_id"), "total": box.get("total")})
            else:
                self.foreign.append({"id": p["id"], "name": p.get("name") or "Sin nombre",
                                     "owner": owner.get("display_name") or owner.get("id", ""),
                                     "url": (p.get("external_urls") or {}).get("spotify", "")})
        return own

    def playlist_tracks(self, pid, progress=None, total=None, base=0.0, span=1.0):
        tracks = []

        def on_page(n, tot):
            tot = tot or total
            if progress and tot:
                progress(f"Leyendo de Spotify: {n}/{tot} canciones", base + span * n / tot)

        for it in self.paged(f"/playlists/{pid}/items", {"limit": 100, "additional_types": "track"}, on_page):
            t = self._track(it.get("item") or it.get("track"))
            if t:
                if it.get("added_at"):
                    t["added_at"] = it["added_at"]  # para saber desde cuándo existe la playlist
                tracks.append(t)
        return tracks

    def my_playlists(self, progress=None, cached=None):
        """Playlists propias y colaborativas con sus canciones, en orden.
        cached: {id: {"snapshot", "tracks"}} lo ya leído. Si Spotify dice que la playlist no cambió
        (mismo snapshot), no se vuelven a pedir sus canciones: así «Analizar todo» hace una fracción
        de las consultas y no se excede el límite de Spotify."""
        result = []
        own = self.list_mine()
        cached = cached or {}
        reused = 0
        budget = 25  # fechas que faltan: una consulta mínima por playlist, de a poco para no exceder el límite
        for i, p in enumerate(own, 1):
            if progress:
                progress(f"Playlist {i}/{len(own)}: {p['name']}", (i - 1) / len(own))
            c = cached.get(p["id"]) or {}
            if p.get("snapshot") and c.get("tracks") is not None and c.get("snapshot") == p["snapshot"]:
                fa = c.get("first_added")
                if not fa and c["tracks"] and not any(t.get("added_at") for t in c["tracks"][:5]) and budget > 0:
                    budget -= 1
                    try:  # cuándo se agregó su primera canción (Spotify no da la fecha de creación)
                        d = self.get(f"/playlists/{p['id']}/items", {"limit": 1, "fields": "items(added_at)"})
                        fa = ((d.get("items") or [{}])[0] or {}).get("added_at")
                    except SpotifyPaused:
                        raise
                    except SpotifyError:
                        fa = None
                result.append({**p, "tracks": c["tracks"], **({"first_added": fa} if fa else {})})
                reused += 1
                continue
            try:
                tracks = self.playlist_tracks(
                    p["id"], (lambda m, f, i=i, name=p["name"]: progress(f"Playlist {i}/{len(own)} «{name}»: {m.split(': ',1)[-1]}", f)) if progress else None,
                    p.get("total"), (i - 1) / len(own), 1 / len(own))
            except SpotifyError as e:
                # no se pierde: se conserva lo que ya había guardado de esa playlist
                log(f"No se pudo leer {p['name']}: {e}")
                result.append({**p, "tracks": None, "error": str(e)})
                continue
            result.append({**p, "tracks": tracks})
        if reused:
            log(f"Spotify: {reused} de {len(own)} playlists sin cambios (no se volvieron a leer)")
        return result

    def liked(self, progress=None):
        if progress:
            progress("Leyendo tus Me gusta…", 0)
        tracks = []

        def on_page(n, tot):
            if progress and tot:
                progress(f"Leyendo tus Me gusta: {n}/{tot}", n / tot)

        for it in self.paged("/me/tracks", {"limit": 50}, on_page):
            t = self._track(it.get("track") or it.get("item"))
            if t:
                if it.get("added_at"):
                    t["added_at"] = it["added_at"]
                tracks.append(t)
        return tracks

    def try_foreign(self, pid):
        """Intenta leer una playlist ajena. Devuelve lista de tracks o None si Spotify no lo permite."""
        try:
            tracks = []
            for it in self.paged(f"/playlists/{pid}/items", {"limit": 100, "additional_types": "track"}):
                t = self._track(it.get("item") or it.get("track"))
                if t:
                    tracks.append(t)
            return tracks
        except SpotifyError as e:
            log(f"Playlist ajena {pid} no legible: {e}")
            return None
