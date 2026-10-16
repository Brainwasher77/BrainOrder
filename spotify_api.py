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
SCOPES = "playlist-read-private playlist-read-collaborative user-library-read"


class SpotifyError(Exception):
    pass


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
        self.token = tok
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(tok), "utf-8")
        os.chmod(TOKEN_FILE, 0o600)

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
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise SpotifyError(f"Spotify rechazó el token ({e.code}): {e.read().decode(errors='ignore')}")

    def _refresh(self):
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
                msg = "Listo, ya puedes volver a SpotiSync." if result["code"] else "No se pudo conectar."
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
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._access()}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and _retry:
                time.sleep(int(e.headers.get("Retry-After", "2")) + 1)
                return self.get(path_or_url, params, _retry - 1)
            if e.code == 401 and _retry:
                self._refresh()
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
                tracks.append(t)
        return tracks

    def my_playlists(self, progress=None):
        """Playlists propias y colaborativas con sus canciones, en orden."""
        result = []
        own = self.list_mine()
        for i, p in enumerate(own, 1):
            if progress:
                progress(f"Playlist {i}/{len(own)}: {p['name']}", (i - 1) / len(own))
            try:
                tracks = self.playlist_tracks(
                    p["id"], (lambda m, f, i=i, name=p["name"]: progress(f"Playlist {i}/{len(own)} «{name}»: {m.split(': ',1)[-1]}", f)) if progress else None,
                    p.get("total"), (i - 1) / len(own), 1 / len(own))
            except SpotifyError as e:
                log(f"No se pudo leer {p['name']}: {e}")
                continue
            result.append({**p, "tracks": tracks})
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
