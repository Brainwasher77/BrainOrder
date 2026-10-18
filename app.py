"""BrainOrder — tus playlists (Spotify, Deezer, archivos…) ↔ tu música ↔ tus programas de DJ.

Ventana nativa de macOS (pywebview). Ejecutar: python app.py
"""
import json
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402
import biblioteca  # noqa: E402
import reglas  # noqa: E402
import historial  # noqa: E402
import destinos  # noqa: E402
import mik_dj  # noqa: E402
import fuentes  # noqa: E402
from destinos.traktor import TraktorError  # noqa: E402
from destinos.serato import SeratoError  # noqa: E402
from destinos.engine import EngineError  # noqa: E402
from fuentes.deezer_src import DeezerError  # noqa: E402
import organizador  # noqa: E402
import plataforma  # noqa: E402
import rekordbox_sync  # noqa: E402
import reportes  # noqa: E402
import deezer  # noqa: E402
import unificar  # noqa: E402
import actualizador  # noqa: E402
from spotify_api import Spotify, SpotifyError, SpotifyPaused  # noqa: E402
import spotify_api  # noqa: E402

CACHE_SPOTIFY = config.SUPPORT_DIR / "spotify_cache.json"
CACHE_ANALYSIS = config.SUPPORT_DIR / "analysis_cache.json"


def _read_json(p, default):
    try:
        return json.loads(Path(p).read_text("utf-8"))
    except Exception:
        return default


def _write_json(p, data):
    """Escritura atómica: quien lee al mismo tiempo ve el archivo viejo completo o el nuevo completo."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    os.replace(tmp, p)


UI_DEFAULTS = {"pl_sort": "spotify",       # orden de la lista de playlists
               "rg_remember": False}       # Reorganizar: recordar lo que dejo donde está (no volver a proponerlo)
UI_CHOICES = {"pl_sort": {"spotify", "missing_desc", "missing_asc", "complete", "incomplete", "organize",
                          "name", "size"}}


def _os_error_text(e):
    """Errores del sistema de archivos explicados en simple."""
    import errno
    if getattr(e, "errno", None) is None:
        return str(e)
    where = f" ({e.filename})" if getattr(e, "filename", None) else ""
    if e.errno == errno.ENOSPC:
        return f"El disco está lleno{where}. Libera espacio y vuelve a intentar: no se perdió nada."
    if e.errno in (errno.EACCES, errno.EPERM):
        return (f"El sistema no dio permiso para tocar un archivo o carpeta{where}. "
                "En Mac: Ajustes del Sistema → Privacidad y seguridad → Acceso total al disco → activa BrainOrder/Python.")
    if e.errno == errno.ENOENT:
        return f"No encontré un archivo o carpeta{where}. ¿Se desconectó un disco externo?"
    if e.errno in (errno.EROFS,):
        return f"Ese disco es de solo lectura{where}."
    if e.errno == errno.EEXIST:
        return f"Ya existe un archivo con ese nombre{where}; no se pisó nada."
    return f"Error del sistema de archivos{where}: {e.strerror or e}"


class Api:
    def __init__(self):
        self._window = None
        self._cfg = config.load()
        biblioteca.load_durations(config.SUPPORT_DIR / "durations.json")
        import armonia
        armonia.load(config.SUPPORT_DIR / "armonia.json")
        # Multitarea segura:
        #  _state: cachés de Spotify y análisis. Se toma solo en tramos cortos (leer/cruzar/escribir),
        #          así varias tareas avanzan a la vez y nunca se pisan los resultados.
        #  _files: mover archivos y tocar Rekordbox. Una sola tarea a la vez; las demás esperan en cola.
        self._state = threading.RLock()
        self._files = threading.Lock()
        self._reg = threading.Lock()
        self._running = {}          # clave de tarea -> id
        self._tl = threading.local()
        self._rev = 0               # versión del análisis (la ventana ignora resultados más viejos)
        self._task_seq = 0
        self._inbox_sig = None
        self._inbox_path = None
        self._an = None             # análisis en memoria (el archivo solo se lee una vez)
        self._inbox_n = (0.0, 0)    # (cuándo, cuántos) último conteo de descargas

    # ---------- utilidades ----------
    def _sp(self):
        return Spotify(self._cfg.get("client_id", ""), self._cfg["redirect_uri"])

    # ---------- progreso por tarea ----------
    # Cada tarea corre en su propio hilo y tiene su propio porcentaje. Las etapas ocupan un tramo
    # [lo, hi] de 0-100 %; las funciones informan su avance dentro de la etapa (0..1).
    def _stage_get(self):
        return getattr(self._tl, "stage", (0.0, 100.0))

    def _set_stage(self, lo, hi, send=True):
        self._tl.stage = (float(lo), float(hi))
        self._tl.outer = None
        if send:
            self._send(None, lo)

    def _sub_stage(self, a, b):
        """Sub-tramo relativo dentro del tramo actual (a, b entre 0 y 1)."""
        if not getattr(self._tl, "outer", None):
            self._tl.outer = self._stage_get()
        lo, hi = self._tl.outer
        self._tl.stage = (lo + (hi - lo) * a, lo + (hi - lo) * b)
        self._send(None, self._tl.stage[0])

    def _progress(self, msg, frac=None):
        lo, hi = self._stage_get()
        pct = None if frac is None else lo + (hi - lo) * max(0.0, min(1.0, float(frac)))
        if msg:
            config.log(msg)
        self._send(msg, pct)

    def _send(self, msg, pct, state="progress"):
        task = getattr(self._tl, "task", None)
        if task is None:
            return  # trabajo en segundo plano (vigilante): no ensucia la pantalla
        if pct is not None:
            pct = round(pct)
            if pct == getattr(self._tl, "last", None) and msg is None and state == "progress":
                return
            self._tl.last = pct
        self._emit({**task, "msg": msg, "pct": pct, "state": state})

    def _emit(self, ev):
        if self._window:
            try:
                self._window.evaluate_js(f"window.onTask && onTask({json.dumps(ev)})")
            except Exception:
                pass

    def _task(self, fn, key, label, files=False):
        """Corre una tarea. Varias pueden correr a la vez; la misma tarea dos veces no.
        files=True: mueve archivos/Rekordbox -> espera su turno en cola."""
        with self._reg:
            if key in self._running:
                return {"ok": False, "dup": True, "error": f"{label}: ya está en curso, espera a que termine."}
            self._task_seq += 1
            tid = self._task_seq
            self._running[key] = tid
        self._tl.task = {"id": tid, "key": key, "label": label}
        self._tl.stage, self._tl.last, self._tl.rev = (0.0, 100.0), None, None
        self._tl.outer = None
        self._send(None, 0, "start")
        got = False
        try:
            if files:
                if not self._files.acquire(blocking=False):
                    self._send("En cola: esperando a que termine otra tarea que mueve archivos…", None, "queued")
                    self._files.acquire()
                got = True
                self._send("Empezando…", 0)
            out = fn() or {}
            if "analysis" in out and self._tl.rev is not None:
                out["rev"] = self._tl.rev
            return {"ok": True, "spotify_paused": spotify_api.paused_until(), **out}
        except SpotifyPaused as e:
            return {"ok": False, "error": str(e), "spotify_paused": spotify_api.paused_until()}
        except (SpotifyError, rekordbox_sync.RekordboxError, unificar.UnifyError, TraktorError, DeezerError,
                SeratoError, EngineError) as e:
            return {"ok": False, "error": str(e)}
        except OSError as e:
            config.log(traceback.format_exc())
            return {"ok": False, "error": _os_error_text(e)}
        except Exception as e:
            config.log(traceback.format_exc())
            return {"ok": False, "error": f"Error inesperado: {e}"}
        finally:
            if got:
                self._files.release()
            with self._reg:
                self._running.pop(key, None)
            self._send(None, None, "done")
            self._tl.task = None

    def running(self):
        with self._reg:
            return {"keys": list(self._running)}

    # ---------- cachés (siempre bajo el candado de estado) ----------
    def _update_sp(self, mutate):
        with self._state:
            data = self._load_sp()
            mutate(data)
            _write_json(CACHE_SPOTIFY, data)
            return data

    def _save_analysis(self, analysis):
        with self._state:
            self._rev += 1
            _write_json(CACHE_ANALYSIS, analysis)
            self._an = analysis
            self._tl.rev = self._rev
            return analysis

    def _analysis(self):
        """Último análisis (de memoria; la primera vez se lee del disco). Solo lectura: no modificarlo."""
        an = self._an
        if an is None:
            an = _read_json(CACHE_ANALYSIS, None)
            if an is not None:
                self._an = an
        return an

    def _inbox_count(self, max_age=5.0):
        """Cuántos audios hay en descargas (el vigilante lo mide cada 4 s; si es reciente se reutiliza)."""
        import time
        t, n = self._inbox_n
        if time.time() - t <= max_age and getattr(self, "_watching", False):
            return n
        n = self._inbox_signature()[1]
        self._inbox_n = (time.time(), n)
        return n

    # ---------- estado ----------
    def get_state(self, rev=None):
        """Estado para la ventana. rev: la versión del análisis que ya tiene la ventana; si coincide
        no se vuelve a mandar el análisis completo (puede pesar varios MB)."""
        sp = self._sp()
        same = rev is not None and rev == self._rev and self._an is not None
        with self._reg:
            running = list(self._running)
        return {
            "connected": sp.connected,
            "settings": {k: self._cfg[k] for k in ("client_id", "redirect_uri", "dest_root", "inbox",
                                                   "library_roots", "liked_name", "include_liked",
                                                   "rekordbox_folder")},
            "analysis": None if same else self._analysis(),
            "rev": self._rev,
            "running": running,
            "foreign": self._cfg.get("foreign", {}),
            "rekordbox_running": rekordbox_sync.rekordbox_running(),
            "home": str(Path.home()),
            "pinned": self._cfg.get("pinned_paths", []),
            "inbox_count": self._inbox_count(),
            "rules": reglas.get(self._cfg),
            "setup_done": bool(self._cfg.get("setup_done")),
            "spotify_paused": spotify_api.paused_until(),
            "ui": {**UI_DEFAULTS, **(self._cfg.get("ui") or {})},
            "rb_mik": {"auto": self._cfg.get("rb_mik_auto", True), "comment": self._cfg.get("rb_mik_comment", "key_energy"),
                       "cues": self._cfg.get("rb_mik_cues", True)},
            "sources": self._sources_status(),
            "destinations": destinos.status(self._cfg),
            "formats": reglas.FORMATS,
            "version": actualizador.local_version(),
            "win": plataforma.IS_WIN,
        }

    def pick_folder(self, current=""):
        """Abre el selector de carpetas de macOS (Finder). Devuelve la ruta o None si se cancela."""
        import webview
        start = current if current and Path(current).exists() else str(Path.home() / "Music")
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        try:
            res = self._window.create_file_dialog(kind, directory=start)
        except Exception as e:
            config.log(f"Selector de carpetas falló: {e}")
            return None
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else str(res)

    def pick_file(self, current="", kind="nml"):
        """Selector de archivo (por ahora: collection.nml de Traktor)."""
        import webview
        start = str(Path(current).parent) if current and Path(current).exists() else str(Path.home() / "Documents")
        mode = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        types = ("Colección de Traktor (*.nml)",) if kind == "nml" else ()
        try:
            res = self._window.create_file_dialog(mode, directory=start, file_types=types)
        except Exception as e:
            config.log(f"Selector de archivos falló: {e}")
            return None
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else str(res)

    # ---------- conexiones: fuentes y destinos ----------
    def _sources_status(self):
        src = self._cfg.get("sources") or {}
        out = {"spotify": {"label": "Spotify", "enabled": (src.get("spotify") or {}).get("enabled", True),
                           "connected": self._sp().connected}}
        for k, m in fuentes.SOURCES.items():
            out[k] = {"label": m.LABEL, "enabled": m.enabled(self._cfg), **(src.get(k) or {})}
        return out

    def _spotify_on(self):
        return (self._cfg.get("sources") or {}).get("spotify", {}).get("enabled", True) and self._sp().connected

    def save_connections(self, payload):
        """Guarda fuentes y destinos. Valida Deezer (por red) antes de guardar."""
        payload = payload or {}
        return self._task(lambda: self._apply_connections(payload), "connections", "Guardar conexiones")

    def _apply_connections(self, payload):
        """Guarda fuentes y destinos (lo usan Conexiones y el asistente)."""
        src = dict(self._cfg.get("sources") or {})
        dst = dict(self._cfg.get("destinations") or {})
        warnings, info = [], {}
        p = payload.get("sources") or {}
        if "spotify" in p:
            src["spotify"] = {"enabled": bool((p["spotify"] or {}).get("enabled", True))}
        if "deezer" in p:
            d = p["deezer"] or {}
            dz = {"enabled": bool(d.get("enabled")), "user": (d.get("user") or "").strip(),
                  "playlists": [x.strip() for x in d.get("playlists") or [] if x.strip()],
                  "include_loved": bool(d.get("include_loved", True))}
            if dz["enabled"] and (dz["user"] or dz["playlists"]):
                self._progress("Comprobando Deezer…", 0.3)
                chk = fuentes.deezer_src.check(dz)
                warnings += chk["errors"]
                info["deezer"] = chk
            src["deezer"] = dz
        if "archivos" in p:
            a = p["archivos"] or {}
            folder = (a.get("folder") or "").strip()
            if a.get("enabled") and folder and not Path(folder).is_dir():
                warnings.append(f"No existe la carpeta {folder}")
            src["archivos"] = {"enabled": bool(a.get("enabled")), "folder": folder}
        mk = payload.get("mik")
        if isinstance(mk, dict):
            if "auto" in mk:
                self._cfg["rb_mik_auto"] = bool(mk["auto"])
            if "cues" in mk:
                self._cfg["rb_mik_cues"] = bool(mk["cues"])
            if mk.get("comment") in ("key_energy", "energy", "none"):
                self._cfg["rb_mik_comment"] = mk["comment"]
        q = payload.get("destinations") or {}
        if "rekordbox" in q:
            v = q["rekordbox"] or {}
            dst["rekordbox"] = {"enabled": bool(v.get("enabled"))}
            if "mik_auto" in v:
                self._cfg["rb_mik_auto"] = bool(v["mik_auto"])
            if v.get("mik_comment") in ("key_energy", "energy", "none"):
                self._cfg["rb_mik_comment"] = v["mik_comment"]
        if "traktor" in q:
            t = q["traktor"] or {}
            nml = (t.get("nml") or "").strip()
            if nml and not nml.lower().endswith(".nml"):
                warnings.append("El archivo de Traktor debe ser collection.nml")
                nml = ""
            dst["traktor"] = {"enabled": bool(t.get("enabled")), "nml": nml}
        for k in ("serato", "engine"):
            if k in q:
                v = q[k] or {}
                d = (v.get("dir") or "").strip()
                if d and not Path(d).is_dir():
                    warnings.append(f"No existe la carpeta {d}")
                    d = ""
                dst[k] = {"enabled": bool(v.get("enabled")), "dir": d}
        if "m3u" in q:
            m = q["m3u"] or {}
            dst["m3u"] = {"enabled": bool(m.get("enabled")), "folder": (m.get("folder") or "").strip()}
        if "folder_name" in payload and (payload["folder_name"] or "").strip():
            self._cfg["rekordbox_folder"] = payload["folder_name"].strip()
        self._cfg["sources"], self._cfg["destinations"] = src, dst
        config.save(self._cfg)
        self._progress("Conexiones guardadas.", 1)
        return {"sources": self._sources_status(), "destinations": destinos.status(self._cfg),
                "warnings": warnings, "info": info, "folder_name": self._cfg.get("rekordbox_folder")}

    # ---------- asistente de primer uso ----------
    def setup_info(self):
        """Lo que el asistente puede sugerir: programas de DJ detectados y carpetas con música."""
        home = Path.home()
        music = home / "Music"
        cands = []
        skip = {"_Serato_", "Engine Library", "PioneerDJ", "rekordbox", "Ableton", "Audio Music Apps", "GarageBand"}
        for base in (music, home / "Downloads", home / "Desktop"):
            try:
                subs = [d for d in base.iterdir() if d.is_dir() and not d.name.startswith((".", "_")) and d.name not in skip]
            except OSError:
                continue
            for d in subs:
                n = 0
                for dirpath, dirnames, filenames in os.walk(d):
                    dirnames[:] = [x for x in dirnames if not x.startswith(".")]
                    n += sum(1 for f in filenames if os.path.splitext(f)[1].lower() in config.AUDIO_EXT)
                    if n >= 5000:
                        break
                if n:
                    cands.append({"path": str(d), "count": n, "capped": n >= 5000})
        cands.sort(key=lambda x: -x["count"])
        cfg_all = {**self._cfg, "destinations": {k: {"enabled": True} for k in destinos.DESTINATIONS}}
        found = {k: {"label": m.LABEL, "available": bool(m.available(cfg_all)) if k != "m3u" else False}
                 for k, m in destinos.DESTINATIONS.items()}
        return {"ok": True, "home": str(home), "music_dirs": cands[:20], "dj": found,
                "defaults": {"dest_root": self._cfg.get("dest_root"), "inbox": self._cfg.get("inbox"),
                             "library_roots": self._cfg.get("library_roots") or [],
                             "client_id": self._cfg.get("client_id", ""), "redirect_uri": self._cfg.get("redirect_uri")}}

    def finish_setup(self, payload):
        payload = payload or {}

        def run():
            dest = (payload.get("dest_root") or "").strip()
            inbox = (payload.get("inbox") or "").strip()
            if not dest or not inbox:
                raise SpotifyError("Elige la carpeta para tu música organizada y la de descargas.")
            self._progress("Creando carpetas…", 0.2)
            for d in (dest, inbox):
                Path(d).expanduser().mkdir(parents=True, exist_ok=True)
            res = self.save_settings({"dest_root": dest, "inbox": inbox, "client_id": payload.get("client_id", ""),
                                      "library_roots": [r for r in payload.get("library_roots") or []
                                                        if r and r not in (dest, inbox)],
                                      "include_liked": payload.get("include_liked", True)})
            if not res.get("ok"):
                raise SpotifyError(res.get("error"))
            self._progress("Guardando conexiones…", 0.5)
            out = self._apply_connections({"sources": payload.get("sources") or {},
                                           "destinations": payload.get("destinations") or {},
                                           "folder_name": payload.get("folder_name") or "BrainOrder"})
            self._cfg["setup_done"] = True
            config.save(self._cfg)
            self._progress("¡Listo!", 1)
            st = self.get_state()
            return {**out, "state": st}
        return self._task(run, "setup", "Configuración inicial")

    def _dj_precheck(self, keys=None):
        """Antes de mover archivos: los programas de DJ que hay que corregir deben estar cerrados."""
        for k in keys or destinos.enabled_keys(self._cfg):
            m = destinos.DESTINATIONS[k]
            if k != "rekordbox" and m.running():
                raise TraktorError(f"{m.LABEL} está abierto. Ciérralo para que BrainOrder pueda corregir sus rutas.")

    def _dj_fix(self, moved, repoint=None):
        out, warn = {}, []
        for k in destinos.enabled_keys(self._cfg):
            if k == "rekordbox":
                continue
            try:
                r = destinos.DESTINATIONS[k].fix_paths(self._cfg, moved, repoint)
                if r:
                    out[k] = r
            except Exception as e:
                warn.append(f"{destinos.DESTINATIONS[k].LABEL}: {e}")
                config.log(f"Corregir rutas en {k} falló: {e!r}")
        return out, warn

    def save_settings(self, s):
        # validar carpetas: descargas y playlists no pueden ser la misma ni estar una dentro de la otra
        new_inbox = Path((s.get("inbox") or self._cfg["inbox"]).strip()).expanduser()
        new_dest = Path((s.get("dest_root") or self._cfg["dest_root"]).strip()).expanduser()
        try:
            a, b = new_inbox.resolve(), new_dest.resolve()
            if a == b or a in b.parents or b in a.parents:
                return {"ok": False, "error": "La carpeta de descargas y la de playlists no pueden ser la misma "
                                              "ni estar una dentro de la otra. Elige otra."}
        except Exception:
            pass
        before = (self._cfg.get("inbox"), self._cfg.get("dest_root"), list(self._cfg.get("library_roots", [])))
        for k in ("client_id", "dest_root", "inbox", "liked_name", "rekordbox_folder"):
            if k in s and isinstance(s[k], str):
                self._cfg[k] = s[k].strip()
        if "include_liked" in s:
            self._cfg["include_liked"] = bool(s["include_liked"])
        if "library_roots" in s:
            roots = s["library_roots"]
            if isinstance(roots, str):
                roots = [r.strip() for r in roots.splitlines() if r.strip()]
            self._cfg["library_roots"] = roots
        config.save(self._cfg)
        after = (self._cfg.get("inbox"), self._cfg.get("dest_root"), list(self._cfg.get("library_roots", [])))
        res = {"ok": True, "inbox_count": self._inbox_signature()[1], "analysis": None}
        if after != before:
            # cambiaron las carpetas: el vigilante toma la nueva como punto de partida (sin avisar de
            # todo lo que ya había) y los estados se recalculan en segundo plano
            self._inbox_sig = None
            self._inbox_n = (0.0, 0)
            self._inbox_path = self._cfg.get("inbox")

            def refresh():
                try:
                    if any(p.get("tracks") is not None for p in self._load_sp()["playlists"]):
                        self._build_analysis(light=True, quiet=True)
                    self._inbox_sig, n = self._inbox_signature()
                    self._emit_inbox(n, [])
                except Exception as e:
                    config.log(f"recalcular tras Ajustes: {e!r}")
            threading.Thread(target=refresh, daemon=True).start()
        return res

    # ---------- Spotify ----------
    def connect(self):
        def run():
            me = self._sp().login()
            return {"user": me.get("display_name") or me.get("id")}
        return self._task(run, "connect", "Conectar Spotify")

    def disconnect(self):
        self._sp().logout()
        return {"ok": True}

    def set_foreign_choice(self, pid, choice):
        f = self._cfg.setdefault("foreign", {})
        if pid in f:
            f[pid]["choice"] = choice
            config.save(self._cfg)
        return {"ok": True}

    # ---------- análisis ----------
    # ---------- datos de Spotify en caché ----------
    def _load_sp(self):
        """Caché de Spotify: {"playlists": [{id, name, snapshot, analyzed_snapshot, tracks|None, liked?}], "foreign_ok": [...]}"""
        data = _read_json(CACHE_SPOTIFY, None) or {}
        pls = list(data.get("playlists") or [])
        if data.get("liked") is not None and not any(p.get("id") == "liked" for p in pls):  # caché antiguo
            pls.append({"id": "liked", "name": self._cfg.get("liked_name", "Me gusta"), "liked": True,
                        "tracks": data["liked"]})
        for p in pls:
            if p.get("tracks") is not None and "analyzed_snapshot" not in p:
                p["analyzed_snapshot"] = p.get("snapshot")
        return {"playlists": pls, "foreign_ok": data.get("foreign_ok") or []}

    def _liked_meta(self, sp):
        """Me gusta no tiene «snapshot» en Spotify: se arma con el total y la fecha del último agregado."""
        try:
            d = sp.get("/me/tracks", {"limit": 1})
            total = d.get("total", 0)
            last = ((d.get("items") or [{}])[0] or {}).get("added_at") or ""
        except SpotifyPaused:
            raise
        except SpotifyError:
            total, last = None, ""
        return {"id": "liked", "name": self._cfg.get("liked_name", "Me gusta"), "liked": True,
                "snapshot": f"n{total}-{last}" if total is not None else None, "total": total}

    def _register_foreign(self, sp):
        known = self._cfg.setdefault("foreign", {})
        for f in sp.foreign:
            if f["id"] not in known:
                known[f["id"]] = {**f, "choice": "preguntar"}
            else:
                known[f["id"]].update(name=f["name"], owner=f["owner"], url=f["url"])
        config.save(self._cfg)
        return known

    def _compute(self, progress=None):
        """Cruce local de la caché de Spotify con tus archivos (sin red). Llamar con _state tomado."""
        sp_data = self._load_sp()
        include_liked = self._cfg.get("include_liked")
        meta = {p["id"]: p for p in sp_data["playlists"]}
        rules = reglas.get(self._cfg)
        loaded = [p for p in sp_data["playlists"]
                  if p.get("tracks") is not None and (include_liked or p["id"] != "liked")
                  and not reglas.ignored(rules, p["id"])]
        loaded = [{**p, "name": self._cfg.get("liked_name", "Me gusta") if p["id"] == "liked" else p["name"]}
                  for p in loaded] + list(sp_data.get("foreign_ok", []))
        result = biblioteca.analyze(loaded, self._cfg, progress)
        deezer.add_links(result, offline=True)  # links ya conocidos
        by_id = {a["id"]: a for a in result}
        analysis = []
        for p in sp_data["playlists"]:
            if p["id"] == "liked" and not include_liked:
                continue
            a = by_id.get(p["id"])
            if a is None:  # todavía sin analizar, o ignorada en Reglas (se trata igual: no se toca)
                name = self._cfg.get("liked_name", "Me gusta") if p["id"] == "liked" else p["name"]
                a = {"id": p["id"], "name": name, "tracks": [], "pending": True, "liked": p["id"] == "liked",
                     "folder": str(biblioteca.resolve_folder(Path(self._cfg["dest_root"]), name)),
                     "ignored": reglas.ignored(rules, p["id"])}
            a["snapshot"] = p.get("snapshot")
            a["source"] = p.get("source") or fuentes.source_of(p["id"])
            a["url"] = p.get("url")
            a["analyzed_snapshot"] = p.get("analyzed_snapshot")
            a["total"] = p.get("total")
            analysis.append(a)
        analysis += [a for a in result if a["id"] not in meta]  # playlists ajenas integradas
        return analysis

    def _attach_reports(self, analysis):
        for pl in analysis:
            txt = Path(pl["folder"]) / reportes.TXT_NAME
            pl["report"] = str(txt) if txt.exists() else None

    def _build_analysis(self, focus=None, light=False, quiet=False):
        """Cruza la caché de Spotify con tus archivos y guarda el análisis.
        focus: ids de playlists a las que se les buscan links de Deezer y se les escribe el .txt
               (None = todas). light=True: solo cruce local (rápido).
        Con varias tareas a la vez: el cruce y la escritura van con candado (tramos cortos) y la
        búsqueda en Deezer (lenta, por red) va sin candado, así no frena a las demás."""
        prog = None if quiet else self._progress
        if light:
            with self._state:
                a = self._compute(prog)
                self._attach_reports(a)
                return self._save_analysis(a)
        self._sub_stage(0.0, 0.45)
        with self._state:
            a = self._compute(prog)
        rows = [r for pl in a if not pl.get("pending") and (focus is None or pl["id"] in focus)
                for r in pl["tracks"] if r["status"] == "missing"]
        self._sub_stage(0.45, 0.95)
        deezer.add_links([{"tracks": rows}], prog)
        self._sub_stage(0.95, 1.0)
        with self._state:
            self._progress("Guardando y escribiendo la lista de faltantes…", 0)
            a = self._compute(None)  # re-cruce rápido con los archivos de este momento
            reportes.write_reports([p for p in a if focus is None or p["id"] in focus], self._cfg)
            self._attach_reports(a)
            self._progress(None, 1)
            return self._save_analysis(a)

    # ---------- analizar ----------
    def list_playlists(self):
        """Trae solo la lista de tus playlists (sin canciones). Rápido."""
        def run():
            self._progress("Leyendo la lista de tus playlists…")
            metas, warnings, known, spotify_ok = self._list_all_sources()

            def merge(data):
                old = {p["id"]: p for p in data["playlists"]}
                new = []
                for m in metas:
                    o = old.get(m["id"]) or {}
                    new.append({**m, "tracks": o.get("tracks"), "analyzed_snapshot": o.get("analyzed_snapshot")})
                if not spotify_ok:  # Spotify apagado o sin conexión: se conserva lo que ya había
                    new = [p for p in data["playlists"] if fuentes.source_of(p["id"]) == "spotify"] + new
                data["playlists"] = new
            self._update_sp(merge)
            analysis = self._build_analysis(light=True)
            self._progress(f"{len(metas)} playlists. Elige una y dale Analizar, o Analizar todo.")
            return {"analysis": analysis, "foreign": known, "warnings": warnings,
                    "ask_foreign": [pid for pid, f in known.items() if f.get("choice") == "preguntar"]}
        return self._task(run, "list", "Cargar playlists")

    def _list_all_sources(self):
        """Metadatos de las playlists de todas las fuentes activas. -> (metas, avisos, ajenas, spotify_ok)"""
        metas, warnings, known, spotify_ok = [], [], self._cfg.get("foreign", {}), False
        if self._spotify_on():
            try:
                sp = self._sp()
                own = sp.list_mine()
                metas += [{**m, "source": "spotify"} for m in own]
                if self._cfg.get("include_liked"):
                    metas.append({**self._liked_meta(sp), "source": "spotify"})
                known = self._register_foreign(sp)
                spotify_ok = True
            except SpotifyPaused as e:
                warnings.append(str(e))  # se conserva la lista de Spotify que ya había
        for k, m in fuentes.SOURCES.items():
            if not m.enabled(self._cfg):
                continue
            try:
                metas += m.list_playlists(self._cfg, self._progress)
            except Exception as e:
                warnings.append(f"{m.LABEL}: {e}")
                config.log(f"Fuente {k} falló: {e!r}")
        if not spotify_ok and not any(m.enabled(self._cfg) for m in fuentes.SOURCES.values()) \
                and not spotify_api.paused_until():
            raise SpotifyError("No hay ninguna fuente activa. Conecta Spotify o activa Deezer / archivos en Conexiones.")
        return metas, warnings, known, spotify_ok

    def _read_tracks(self, entry):
        """Canciones de una playlist desde su fuente."""
        src = entry.get("source") or fuentes.source_of(entry["id"])
        if src == "spotify":
            sp = self._sp()
            if entry["id"] == "liked":
                entry.update(self._liked_meta(sp))
                return sp.liked(self._progress)
            return sp.playlist_tracks(entry["id"], self._progress, entry.get("total"))
        m = fuentes.SOURCES[src]
        return m.tracks(self._cfg, entry, self._progress)

    def analyze_playlist(self, pid):
        """Lee de Spotify SOLO esta playlist y la cruza con tus archivos."""
        def run():
            if reglas.ignored(reglas.get(self._cfg), pid):
                raise SpotifyError("Esta playlist está ignorada en Reglas. Actívala allí para analizarla.")
            entry = dict(next((p for p in self._load_sp()["playlists"] if p["id"] == pid), None) or {})
            if not entry:
                raise SpotifyError("No encontré esa playlist. Dale a ⟳ para recargar la lista.")
            src = entry.get("source") or fuentes.source_of(pid)
            label = "Spotify" if src == "spotify" else fuentes.SOURCES[src].LABEL
            self._set_stage(0, 40)
            self._progress(f"Leyendo «{entry['name']}» de {label}…", 0)
            if src == "spotify" and not self._sp().connected:
                raise SpotifyError("Spotify no está conectado. Conéctalo para leer esta playlist.")
            tracks = self._read_tracks(entry)

            def put(data):  # guardar sobre la caché MÁS RECIENTE (otra tarea pudo cambiarla)
                cur = next((p for p in data["playlists"] if p["id"] == pid), None)
                if cur is None:
                    cur = {k: v for k, v in entry.items() if k != "tracks"}
                    data["playlists"].append(cur)
                cur.update({k: v for k, v in entry.items() if k in ("snapshot", "total", "name")})
                cur["tracks"] = tracks
                cur["analyzed_snapshot"] = cur.get("snapshot")
            self._update_sp(put)
            self._set_stage(40, 100)
            analysis = self._build_analysis(focus={pid})
            self._set_stage(0, 100, send=False)
            self._progress(f"«{entry['name']}» analizada.", 1)
            return {"analysis": analysis}
        name = next((p.get("name") for p in self._load_sp()["playlists"] if p["id"] == pid), "playlist")
        return self._task(run, f"analyze:{pid}", f"Analizar «{name}»")

    def analyze(self):
        """Analizar todo: todas tus playlists y Me gusta."""
        def run():
            self._set_stage(0, 45)
            rules = reglas.get(self._cfg)
            playlists, foreign_ok, warnings = [], None, []
            known = self._cfg.get("foreign", {})
            spotify_ok = self._spotify_on()
            if spotify_ok:
              try:
                sp = self._sp()
                self._sub_stage(0, 0.7)
                cached = {p["id"]: {"snapshot": p.get("analyzed_snapshot"), "tracks": p.get("tracks")}
                          for p in self._load_sp()["playlists"]}
                playlists = [{**p, "source": "spotify"} for p in sp.my_playlists(self._progress, cached)]
                for p in playlists:
                    p["analyzed_snapshot"] = p.get("snapshot")
                    if p.get("error"):
                        warnings.append(f"Spotify «{p['name']}»: {p.pop('error')} (se mantiene lo último que leí)")
                if self._cfg.get("include_liked"):
                    lm = {**self._liked_meta(sp), "source": "spotify"}
                    old = cached.get("liked") or {}
                    if lm["snapshot"] and old.get("tracks") is not None and old.get("snapshot") == lm["snapshot"]:
                        lm["tracks"] = old["tracks"]  # Me gusta no cambió: no se vuelve a leer entera
                    else:
                        lm["tracks"] = sp.liked(self._progress)
                    lm["analyzed_snapshot"] = lm["snapshot"]
                    playlists.append(lm)
                known = self._register_foreign(sp)
                foreign_ok = []
                for pid, f in known.items():
                    if f.get("choice") != "integrar":
                        continue
                    self._progress(f"Intentando leer playlist ajena: {f['name']}")
                    tracks = sp.try_foreign(pid)
                    if tracks:
                        f["status"] = "integrada"
                        foreign_ok.append({"id": pid, "name": f["name"], "tracks": tracks})
                    else:
                        f["status"] = "pendiente"  # Spotify no deja leerla: hay que copiarla a una propia
                config.save(self._cfg)
              except SpotifyPaused as e:
                # Spotify en pausa: se sigue con lo último leído (y con Deezer, archivos y tu música)
                warnings.append(str(e))
                spotify_ok, playlists, foreign_ok = False, [], None
            # otras fuentes (Deezer, archivos)
            self._sub_stage(0.7, 1.0)
            others = []
            for k, m in fuentes.SOURCES.items():
                if not m.enabled(self._cfg):
                    continue
                try:
                    metas = m.list_playlists(self._cfg, self._progress)
                except Exception as e:
                    warnings.append(f"{m.LABEL}: {e}")
                    continue
                for i, meta in enumerate(metas):
                    if meta.get("error") or reglas.ignored(rules, meta["id"]):
                        others.append({**meta, "tracks": None})
                        continue
                    try:
                        tr = m.tracks(self._cfg, meta, None)
                        self._progress(f"{m.LABEL}: {meta['name']}", (i + 1) / max(1, len(metas)))
                        others.append({**meta, "tracks": tr, "analyzed_snapshot": meta.get("snapshot")})
                    except Exception as e:
                        warnings.append(f"{m.LABEL} «{meta['name']}»: {e}")
                        others.append({**meta, "tracks": None})
            if not spotify_ok and not any(m.enabled(self._cfg) for m in fuentes.SOURCES.values()) \
                    and not spotify_api.paused_until():
                raise SpotifyError("No hay ninguna fuente activa. Conecta Spotify o activa Deezer / archivos en Conexiones.")

            def put(data):
                old = {p["id"]: p for p in data["playlists"]}
                for p in playlists + others:  # lo que no se pudo leer conserva lo guardado
                    o = old.get(p["id"]) or {}
                    if p.get("tracks") is None and o.get("tracks") is not None:
                        p["tracks"], p["analyzed_snapshot"] = o["tracks"], o.get("analyzed_snapshot")
                keep = [] if spotify_ok else [p for p in data["playlists"] if fuentes.source_of(p["id"]) == "spotify"]
                data["playlists"] = (playlists if spotify_ok else keep) + others
                if foreign_ok is not None:
                    data["foreign_ok"] = foreign_ok
            self._update_sp(put)
            self._set_stage(45, 100)
            analysis = self._build_analysis()
            self._set_stage(0, 100, send=False)
            self._progress("Análisis listo.", 1)
            return {"analysis": analysis, "foreign": known, "warnings": warnings,
                    "ask_foreign": [pid for pid, f in known.items() if f.get("choice") == "preguntar"]}
        return self._task(run, "analyze:all", "Analizar todo")

    # ---------- reglas ----------
    def _roots(self):
        out = []
        for r in [self._cfg.get("dest_root"), self._cfg.get("inbox")] + list(self._cfg.get("library_roots") or []):
            if r and r not in out:
                out.append(r)
        return out

    def preview_rules(self, rules):
        """«Probar»: cuántos archivos quedan fuera con estas reglas (no guarda nada)."""
        r, errs = reglas.clean(rules or {})

        def run():
            ex = reglas.Excluder(r)
            roots = self._roots()
            out, total_in, total_out, sample = [], 0, 0, []
            for i, root in enumerate(roots):
                self._progress(f"Revisando {Path(root).name}…", i / max(1, len(roots)))
                if not Path(root).is_dir():
                    out.append({"root": root, "exists": False, "in": 0, "out": 0})
                    continue
                n_in = n_out = 0
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                    dir_out = ex.dir_excluded(dirpath) if dirpath != root else False
                    for fn in filenames:
                        if fn.startswith(".") or Path(fn).suffix.lower() not in config.AUDIO_EXT:
                            continue
                        p = os.path.join(dirpath, fn)
                        if dir_out or ex.file_excluded(p, biblioteca.duration):
                            n_out += 1
                            if len(sample) < 12:
                                sample.append(p)
                        else:
                            n_in += 1
                out.append({"root": root, "exists": True, "in": n_in, "out": n_out})
                total_in += n_in
                total_out += n_out
            biblioteca.save_durations()
            return {"roots": out, "in": total_in, "out": total_out, "sample": sample, "warnings": errs}
        return self._task(run, "rules_preview", "Probar reglas")

    def save_rules(self, rules):
        r, errs = reglas.clean(rules or {})

        def run():
            self._cfg["rules"] = r
            config.save(self._cfg)
            self._inbox_sig = None
            self._inbox_n = (0.0, 0)
            analysis = None
            if any(p.get("tracks") is not None for p in self._load_sp()["playlists"]):
                self._progress("Aplicando las reglas a tu música…", 0)
                analysis = self._build_analysis(light=True)
                with self._state:
                    reportes.write_reports(analysis, self._cfg)
            self._progress("Reglas guardadas.", 1)
            return {"rules": r, "warnings": errs, "analysis": analysis,
                    "inbox_count": self._inbox_signature()[1]}
        return self._task(run, "rules", "Aplicar reglas")

    # ---------- organizar ----------
    def organize(self, targets=True, pid=None, extra=None):
        label = "Organizar" + (f" «{next((p['name'] for p in (self._analysis() or []) if p['id'] == pid), '')}»" if pid else " descargas")
        """Organiza todo, o solo una playlist (pid).
        extra (solo en el general): {"groups": [nombres de subcarpetas de descargas],
                                     "files": [{"src", "dest"}]} para descargas sin playlist."""
        def run():
            # mientras se mueven archivos, nadie más cruza ni guarda (sus resultados quedarían viejos)
            with self._state:
                self._set_stage(0, 50)
                sp_data = self._load_sp()
                analysis = self._analysis() or []
                subset = [p for p in analysis if p["id"] == pid] if pid else analysis
                if pid and not subset:
                    raise SpotifyError("No encontré esa playlist.")
                files = organizador.organize(subset, self._cfg, self._progress) if subset else \
                    {"moved": 0, "duplicates": 0, "errors": []}
                extra_res = None
                if extra and not pid:
                    inbox = Path(self._cfg["inbox"]).resolve()
                    dest_root = Path(self._cfg["dest_root"])
                    groups = []
                    for name in extra.get("groups") or []:
                        folder = (inbox / name).resolve()
                        if folder.parent == inbox and folder.is_dir() and not name.startswith("_"):
                            groups.append((str(folder), str(biblioteca.resolve_folder(dest_root, name.strip()))))
                    sel = []
                    for it in extra.get("files") or []:
                        src, dest = Path(it.get("src", "")).resolve(), Path(it.get("dest", ""))
                        if inbox in src.parents and src.is_file() and dest.is_dir():
                            sel.append((str(src), str(dest)))
                    if groups or sel:
                        extra_res = organizador.move_unmatched(groups, sel, self._cfg, self._progress)
                journal = files.pop("journal", []) + ((extra_res or {}).pop("journal", []) if extra_res else [])
                op_id = historial.record("organize", label, journal)
                if not sp_data["playlists"] or not analysis:
                    self._inbox_sig = None
                    self._inbox_n = (0.0, 0)
                    return {"files": files, "extra": extra_res, "rekordbox": None, "rekordbox_error": None,
                            "analysis": analysis or None, "op_id": op_id}
                self._progress("Re-escaneando tu música…")
                self._set_stage(50, 85)
                analysis = self._build_analysis(light=True)
            self._set_stage(85, 100)
            # programas de DJ: True = todos los activos; lista = los marcados en la ventana
            keys = destinos.enabled_keys(self._cfg) if targets is True else \
                [k for k in (targets or []) if k in destinos.enabled_keys(self._cfg)]
            dj, target = {}, ([p for p in analysis if p["id"] == pid] if pid else analysis)
            for j, k in enumerate(keys):
                m = destinos.DESTINATIONS[k]
                self._sub_stage(j / len(keys), (j + 1) / len(keys))
                try:
                    cfg_k = self._cfg
                    if k == "rekordbox":
                        # no pisar playlists con cambios tuyos en Rekordbox que aún no decidiste
                        pend = self._rb_pending_pids()
                        cfg_k = {**self._cfg, "_rb_pending": pend}
                    st = m.sync(target, cfg_k, self._progress)
                    if k == "rekordbox" and isinstance(st, dict):
                        import rb_cambios
                        base = st.pop("baseline", None)
                        rb_cambios.merge_baseline(base)
                        synced = {v["pid"] for v in (base or {}).values()}
                        if self._cfg.get("rb_revert"):
                            self._cfg["rb_revert"] = [p for p in self._cfg["rb_revert"] if p not in synced]
                            config.save(self._cfg)
                    if isinstance(st, dict) and k in mik_dj.PROGRAMS and self._cfg.get("rb_mik_auto", True):
                        # lo que analizó Mixed In Key (key, energía y hot cues) va también a ese programa
                        try:
                            # el programa ya se respaldó al sincronizar: no se hace otro respaldo enorme
                            mres = mik_dj.run(self._cfg, k, apply=True, progress=self._progress,
                                              backup=not st.get("backup"))
                            sm = mik_dj.summary(mres["changes"])
                            st["mik"], st["mik_cues"] = sm["count"], sm["cues"]
                        except Exception as e:
                            st["mik_error"] = str(e)
                    dj[k] = {"label": m.LABEL, "stats": st}
                except Exception as e:
                    config.log(f"{m.LABEL} falló: {e!r}")
                    dj[k] = {"label": m.LABEL, "error": str(e)}
            rb = (dj.get("rekordbox") or {}).get("stats")
            rb_error = (dj.get("rekordbox") or {}).get("error")
            with self._state:
                reportes.write_reports([p for p in analysis if not pid or p["id"] == pid], self._cfg)
            self._inbox_sig = None  # forzar que el vigilante vuelva a mirar descargas
            self._inbox_n = (0.0, 0)
            self._progress("Organización terminada.", 1)
            return {"files": files, "extra": extra_res, "rekordbox": rb, "rekordbox_error": rb_error,
                    "dj": dj, "analysis": analysis, "op_id": op_id}
        return self._task(run, f"organize:{pid or 'all'}", label, files=True)

    # ---------- historial y deshacer ----------
    def history(self):
        return {"ok": True, "ops": historial.list_ops()}

    def undo(self, op_id):
        op = historial.get(op_id)
        label = (op or {}).get("label") or "operación"

        def run():
            if not op:
                raise unificar.UnifyError("No encontré esa operación en el historial.")
            if op.get("undone"):
                raise unificar.UnifyError("Esa operación ya se deshizo.")
            todo, skipped = historial.plan_undo(op)
            if not todo:
                return {"restored": 0, "skipped": skipped, "analysis": None}
            back = {cur: orig for cur, orig in todo}
            # Rekordbox: si alguna pista movida está en la librería, hay que corregirla (cerrado y con respaldo)
            rb = unificar.rb_index(self._progress) or {}
            rb_change = {cur: orig for cur, orig in back.items() if cur in rb}
            if rb_change and rekordbox_sync.rekordbox_running():
                raise rekordbox_sync.RekordboxError("Rekordbox está abierto. Ciérralo y vuelve a deshacer: hay pistas de tu librería entre los archivos.")
            self._dj_precheck()
            with self._state:
                self._set_stage(0, 60)
                protect = [self._cfg.get("dest_root"), self._cfg.get("inbox")] + list(self._cfg.get("library_roots") or [])
                done = historial.apply_undo(op, todo, protect, self._progress)
                self._set_stage(60, 80)
                rb_stats, warnings = None, []
                if rb_change:
                    try:
                        self._progress("Corrigiendo rutas en Rekordbox…")
                        rekordbox_sync.backup()
                        rb_stats = unificar._rb_apply({k: v for k, v in rb_change.items() if k in done}, {}, {})
                    except Exception as e:
                        warnings.append(f"Rekordbox: {e}")
                dj, w2 = self._dj_fix(done)
                warnings += w2
                self._set_stage(80, 100)
                self._progress("Actualizando el análisis…")
                analysis = None
                if any(p.get("tracks") is not None for p in self._load_sp()["playlists"]):
                    analysis = self._build_analysis(light=True)
                    reportes.write_reports(analysis, self._cfg)
            self._inbox_sig = None
            self._inbox_n = (0.0, 0)
            self._progress("Listo.", 1)
            return {"restored": len(done), "skipped": skipped, "rekordbox": rb_stats, "dj": dj,
                    "warnings": warnings, "analysis": analysis}
        return self._task(run, f"undo:{op_id}", f"Deshacer «{label}»", files=True)

    # ---------- reorganizar por playlist ----------
    def relocate(self, pid, moves, keep, remember=True):
        """moves: [{src, dest}] archivos a mover; keep: rutas que se dejan donde están."""
        def run():
            with self._state:
                analysis = self._analysis() or []
                pl = next((p for p in analysis if p["id"] == pid), None)
                if not pl:
                    raise SpotifyError("No encontré esa playlist. Vuelve a analizarla.")
                valid_src = {r["source"] for r in pl["tracks"] if r.get("source") and r["status"] in ("ok", "elsewhere")}
                allowed = {a["folder"] for a in analysis} | {r["dest_dir"] for r in pl["tracks"] if r.get("dest_dir")}
                roots = [Path(x).resolve() for x in [self._cfg.get("dest_root")] + list(self._cfg.get("library_roots") or []) if x]

                def dest_ok(dest):
                    """Carpeta de una playlist, o una carpeta que elegiste dentro de tu biblioteca (no descargas)."""
                    if dest in allowed:
                        return True
                    try:
                        d = Path(dest).resolve()
                    except (OSError, TypeError):
                        return False
                    inbox = Path(self._cfg["inbox"]).resolve()
                    return d.is_dir() and d != inbox and inbox not in d.parents and \
                        any(d == r or r in d.parents for r in roots) and "_duplicados" not in d.parts
                ops, seen = [], set()
                for m in moves or []:
                    src, dest = m.get("src"), m.get("dest")
                    if src in valid_src and dest and dest_ok(dest) and src not in seen and str(Path(src).parent) != dest:
                        ops.append((src, dest))
                        seen.add(src)
                if ops:
                    self._dj_precheck()
                res = organizador.relocate(ops, self._cfg, self._progress) if ops else \
                    {"moved": 0, "skipped": [], "rekordbox": None, "backup": None, "changes": {}}
                okset = {o[0] for o in ops}
                for m in moves or []:
                    if m.get("src") and m["src"] not in okset and str(Path(m["src"]).parent) != m.get("dest"):
                        why = ("esa carpeta no está dentro de tu biblioteca (Ajustes)" if m["src"] in valid_src
                               else "ya no está en esta playlist; vuelve a analizarla")
                        res["skipped"].append({"file": Path(m["src"]).name, "why": why})
                pinned = set(self._cfg.get("pinned_paths", []))
                if remember:
                    pinned |= {p for p in (keep or []) if p in valid_src}
                    # lo que moviste a una carpeta que no es "su" carpeta también queda fijado
                    home = {r["source"]: r.get("dest_dir") for r in pl["tracks"] if r.get("source")}
                    for src, new in res["changes"].items():
                        if str(Path(new).parent) != home.get(src):
                            pinned.add(new)
                res["dj"], res["dj_warnings"] = self._dj_fix(res["changes"]) if res["changes"] else ({}, [])
                res["op_id"] = historial.record("relocate", f"Reorganizar «{pl['name']}»", list(res["changes"].items()))
                pinned -= set(res["changes"])  # las rutas viejas ya no existen
                self._cfg["pinned_paths"] = sorted(pinned)
                config.save(self._cfg)
                analysis = self._build_analysis(light=True)
                reportes.write_reports([p for p in analysis if p["id"] == pid], self._cfg)
                res.pop("changes", None)
                return {"result": res, "analysis": analysis, "pinned": self._cfg["pinned_paths"]}
        return self._task(run, f"relocate:{pid}", "Reorganizar", files=True)

    def save_ui(self, prefs):
        """Preferencias de la ventana (orden de las playlists, recordar en Reorganizar…)."""
        cur = dict(self._cfg.get("ui") or {})
        for k, v in (prefs or {}).items():
            if k not in UI_DEFAULTS:
                continue
            if k in UI_CHOICES and v not in UI_CHOICES[k]:
                continue
            cur[k] = bool(v) if isinstance(UI_DEFAULTS[k], bool) else v
        self._cfg["ui"] = cur
        config.save(self._cfg)
        return {"ok": True, "ui": {**UI_DEFAULTS, **cur}}

    def pin(self, paths):
        """Fijar archivos donde están: Reorganizar no los vuelve a proponer."""
        self._cfg["pinned_paths"] = sorted(set(self._cfg.get("pinned_paths", [])) | set(paths or []))
        config.save(self._cfg)
        return {"ok": True, "pinned": self._cfg["pinned_paths"]}

    def unpin(self, paths):
        self._cfg["pinned_paths"] = sorted(set(self._cfg.get("pinned_paths", [])) - set(paths or []))
        config.save(self._cfg)
        return {"ok": True, "pinned": self._cfg["pinned_paths"]}

    def inbox_status(self):
        """Qué hay en descargas: listos para su playlist, repetidos y sin playlist (por subcarpeta)."""
        sig, n = self._inbox_signature()
        files = [p for p, _, _ in sig]
        analysis = self._analysis() or []
        ready, dups = set(), set()
        for pl in analysis:
            for r in pl["tracks"]:
                if r["status"] == "inbox" and r.get("source"):
                    ready.add(r["source"])
                dups.update(r.get("inbox_dups") or [])
        dups -= ready
        inbox = Path(self._cfg["inbox"])
        dest_root = Path(self._cfg["dest_root"])
        groups, loose = {}, []
        for f in files:
            if f in ready or f in dups:
                continue
            try:
                rel = Path(f).relative_to(inbox)
            except ValueError:
                continue
            if len(rel.parts) > 1:
                groups.setdefault(rel.parts[0], []).append(f)
            else:
                loose.append(f)
        out_groups = []
        for name, fs in sorted(groups.items(), key=lambda x: -len(x[1])):
            dest = biblioteca.resolve_folder(dest_root, name.strip())
            out_groups.append({"name": name, "path": str(inbox / name), "count": len(fs),
                               "dest": str(dest), "dest_exists": dest.exists(),
                               "sample": [Path(x).name for x in fs[:4]]})
        fset = set(files)
        return {"count": n, "ready": len(ready & fset), "dups": len(dups & fset),
                "groups": out_groups, "loose": loose,
                "analyzed": sum(1 for p in analysis if not p.get("pending")),
                "pending": sum(1 for p in analysis if p.get("pending") and not p.get("ignored"))}

    # ---------- vigilante de la carpeta de descargas ----------
    def _inbox_signature(self):
        inbox = Path(self._cfg["inbox"])
        skip = {self._cfg.get("inbox_done", "_organizadas"), "_duplicados"}
        ex = reglas.Excluder({**reglas.get(self._cfg), "min_seconds": 0})  # sin leer duraciones: es cada 4 s
        sig = []
        if not inbox.is_dir():
            return (), 0
        for dirpath, dirnames, filenames in os.walk(inbox):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip
                           and not ex.dir_excluded(os.path.join(dirpath, d))]
            for fn in filenames:
                if fn.startswith(".") or Path(fn).suffix.lower() not in config.AUDIO_EXT:
                    continue
                if ex.file_excluded(os.path.join(dirpath, fn)):
                    continue
                try:
                    st = os.stat(os.path.join(dirpath, fn))
                except OSError:
                    continue
                sig.append((os.path.join(dirpath, fn), st.st_size, int(st.st_mtime)))
        sig.sort()
        return tuple(sig), len(sig)

    def _watch_inbox(self):
        """Cada pocos segundos mira la carpeta de descargas. Si cambió (y el archivo terminó
        de copiarse), recalcula lo que hay por organizar y avisa a la ventana."""
        import time
        self._inbox_sig = None
        self._inbox_n = (0.0, 0)
        self._inbox_path = self._cfg.get("inbox")
        last_seen, stable = None, 0
        while True:
            time.sleep(4)
            try:
                if self._cfg.get("inbox") != self._inbox_path:   # cambiaste la carpeta en Ajustes
                    self._inbox_path = self._cfg.get("inbox")
                    self._inbox_sig, last_seen, stable = None, None, 0
                sig, n = self._inbox_signature()
                self._inbox_n = (time.time(), n)
                if sig != last_seen:          # algo cambió: esperar a que deje de cambiar (descarga en curso)
                    last_seen, stable = sig, 0
                    continue
                stable += 1
                if sig == self._inbox_sig or stable < 1:
                    continue
                prev = set(p for p, _, _ in (self._inbox_sig or ()))
                nuevos = [p for p, _, _ in sig if p not in prev] if self._inbox_sig is not None else []
                if self._files.locked():
                    continue  # se están moviendo archivos: se revisa cuando termine
                if not self._state.acquire(blocking=False):
                    continue  # otra tarea está guardando; se reintenta en unos segundos
                try:
                    self._inbox_sig = sig
                    if any(p.get("tracks") is not None for p in self._load_sp()["playlists"]):
                        self._build_analysis(light=True, quiet=True)
                finally:
                    self._state.release()
                self._emit_inbox(n, nuevos)
            except Exception as e:
                config.log(f"vigilante de descargas: {e!r}")

    def _emit_inbox(self, n, nuevos):
        if self._window:
            payload = json.dumps({"count": n, "new": [Path(p).name for p in nuevos][:20],
                                  "new_count": len(nuevos), "rev": self._rev})
            try:
                self._window.evaluate_js(f"window.onInboxChange && onInboxChange({payload})")
            except Exception:
                pass

    def start_watch(self):
        if getattr(self, "_watching", False):
            return {"ok": True}
        self._watching = True
        threading.Thread(target=self._watch_inbox, daemon=True).start()
        threading.Thread(target=self._watch_rekordbox, daemon=True).start()
        threading.Thread(target=self._watch_mik, daemon=True).start()
        return {"ok": True}

    # ---------- cambios hechos a mano en Rekordbox -> ¿también en Spotify? ----------
    def _rb_changes(self):
        """(cambios, estado actual). La primera vez solo toma la foto (no hay nada que preguntar)."""
        import rb_cambios
        if not rekordbox_sync.RB_DIR.joinpath("master.db").exists():
            return [], None
        if not destinos.DESTINATIONS["rekordbox"].enabled(self._cfg):
            return [], None
        state = rb_cambios.read_state(self._cfg)
        analysis = self._analysis() or []
        if not rb_cambios.BASELINE.exists():
            by_name = {p["name"]: p["id"] for p in analysis}
            rb_cambios.save_baseline({rid: {"pid": by_name.get(v["name"]), "name": v["name"], "paths": v["paths"]}
                                      for rid, v in (state or {}).items()})
            return [], state
        return rb_cambios.diff(rb_cambios.load_baseline(), state, analysis), state

    def _rb_pending_pids(self):
        try:
            changes, _ = self._rb_changes()
        except Exception as e:
            config.log(f"No pude revisar cambios de Rekordbox: {e!r}")
            return []
        revert = set(self._cfg.get("rb_revert") or [])
        return sorted({c["pid"] for c in changes if c.get("pid")} - revert)

    def _watch_rekordbox(self):
        """Cada 15 s mira si cambió la librería de Rekordbox; si hay cambios tuyos en la carpeta de BrainOrder, avisa."""
        import time
        import rb_cambios
        last_mtime, last_ids = None, None
        while True:
            time.sleep(15)
            try:
                mt = rb_cambios.db_mtime()
                if mt is None or mt == last_mtime or self._files.locked():
                    continue
                last_mtime = mt
                changes, _ = self._rb_changes()
                ids = sorted(c["id"] for c in changes)
                if ids and ids != last_ids and self._window:
                    payload = json.dumps({"count": len(changes), "names": sorted({c["name"] for c in changes})[:5]})
                    self._window.evaluate_js(f"window.onRbChanges && onRbChanges({payload})")
                last_ids = ids
            except Exception as e:
                config.log(f"vigilante de Rekordbox: {e!r}")

    def _spotify_uri_for(self, path, analysis, sp, cache):
        """Archivo local -> spotify:track:… (de tus playlists, por ISRC o buscando artista + título)."""
        import re as _re
        if path in cache:
            return cache[path]
        for pl in analysis:
            if pl.get("source", "spotify") != "spotify":
                continue
            for r in pl["tracks"]:
                if r.get("source") == path and _re.fullmatch(r"[A-Za-z0-9]{22}", r.get("id", "")):
                    cache[path] = ({"uri": f"spotify:track:{r['id']}", "name": r["name"],
                                    "artists": r["artists"], "how": "de tus playlists"})
                    return cache[path]
        isrc = None
        try:
            import mutagen
            mf = mutagen.File(path)
            t = mf.tags if mf is not None else None
            if t is not None:
                if hasattr(t, "getall"):
                    f = t.getall("TSRC")
                    isrc = str(f[0].text[0]) if f else None
                else:
                    v = t.get("isrc") or t.get("ISRC") or t.get("----:com.apple.iTunes:ISRC")
                    isrc = (bytes(v[0]).decode() if v and not isinstance(v[0], str) else (v[0] if v else None))
        except Exception:
            isrc = None
        artist, title = biblioteca.parse_file(Path(path))
        hit, how = None, None
        try:
            if isrc:
                res = sp.search_track(isrc=isrc.strip())
                hit, how = (res[0], "por ISRC") if res else (None, None)
            if not hit and title:
                core, ex = biblioteca.core_title(title), biblioteca.extras(title)
                dur = biblioteca.duration(path)
                for t in sp.search_track(artist=artist, title=biblioteca.core_title(title) if not artist else title):
                    if biblioteca.core_title(t["name"]) != core or biblioteca.version_diff(ex, biblioteca.extras(t["name"])):
                        continue
                    if artist and not biblioteca.artist_ok(t["artists"], biblioteca.norm(artist)):
                        continue
                    if dur and t.get("duration_ms") and not biblioteca.same_length(dur, t["duration_ms"] / 1000):
                        continue
                    hit, how = t, "buscando artista y título"
                    break
        except SpotifyError as e:
            config.log(f"búsqueda en Spotify falló para {path}: {e}")
        cache[path] = ({"uri": f"spotify:track:{hit['id']}", "name": hit["name"], "artists": hit["artists"], "how": how}
                       if hit else None)
        return cache[path]

    def rb_check(self):
        """Cambios hechos en Rekordbox que todavía no decidiste qué hacer."""
        try:
            changes, state = self._rb_changes()
        except Exception as e:
            return {"ok": False, "error": f"No pude leer Rekordbox: {e}"}
        self._rb_state = state
        analysis = self._analysis() or []
        by_id = {p["id"]: p for p in analysis}
        for c in changes:
            pl = by_id.get(c.get("pid")) or {}
            c["source"] = pl.get("source") or (fuentes.source_of(c["pid"]) if c.get("pid") else None)
            c["files"] = [Path(p).name for p in c.get("paths") or []][:200]
        sp = self._sp()
        return {"ok": True, "changes": changes, "spotify": {"connected": sp.connected, "can_write": sp.can_write},
                "rekordbox_running": rekordbox_sync.rekordbox_running(), "keep": self._cfg.get("rb_keep") or []}

    def rb_apply(self, decisions):
        """decisions: {id del cambio: "spotify" | "keep" | "revert"}."""
        decisions = decisions or {}

        def run():
            import rb_cambios
            changes, state = self._rb_changes()
            todo = [c for c in changes if decisions.get(c["id"])]
            if not todo:
                return {"done": [], "errors": [], "unresolved": []}
            sp = self._sp()
            analysis = self._analysis() or []
            by_id = {p["id"]: p for p in analysis}
            need_sp = [c for c in todo if decisions[c["id"]] == "spotify"]
            if need_sp and not sp.can_write:
                raise SpotifyError("Para pasar cambios a Spotify reconecta Spotify (Conectar) y acepta el permiso de editar playlists.")
            done, errors, unresolved, accepted, new_pid, refresh, revert = [], [], [], set(), {}, set(), set()
            keep = set(self._cfg.get("rb_keep") or [])
            cache = {}
            for n, c in enumerate(todo, 1):
                d = decisions[c["id"]]
                self._progress(f"{c['name']}: {c['type']}", n / len(todo))
                pid = c.get("pid") or new_pid.get(c["rb_id"])
                try:
                    if d == "keep":
                        if pid:
                            keep.add(pid)
                        accepted.add(c["rb_id"])
                        done.append(f"«{c['name']}»: se queda como está en Rekordbox")
                    elif d == "revert":
                        if pid:
                            revert.add(pid)
                            keep.discard(pid)
                    elif d == "spotify":
                        is_liked = pid == "liked"
                        if c["type"] == "created":
                            uris = []
                            for p in c["paths"]:
                                r = self._spotify_uri_for(p, analysis, sp, cache)
                                (uris.append(r["uri"]) if r else unresolved.append({"playlist": c["name"], "file": Path(p).name}))
                            created = sp.create_playlist(c["name"])
                            new_pid[c["rb_id"]] = created["id"]
                            if uris:
                                sp.add_items(created["id"], uris)
                            refresh.add(created["id"])
                            done.append(f"«{c['name']}»: creada en Spotify con {len(uris)} canciones")
                        elif not pid or (by_id.get(pid) or {}).get("source", "spotify") != "spotify" or \
                                fuentes.source_of(pid) != "spotify":
                            errors.append(f"«{c['name']}» no viene de Spotify: el cambio se queda solo en Rekordbox")
                            if pid:
                                keep.add(pid)
                        elif c["type"] == "added":
                            uris = []
                            for p in c["paths"]:
                                r = self._spotify_uri_for(p, analysis, sp, cache)
                                (uris.append(r["uri"]) if r else unresolved.append({"playlist": c["name"], "file": Path(p).name}))
                            if uris:
                                sp.save_to_library(uris) if is_liked else sp.add_items(pid, uris)
                            refresh.add(pid)
                            done.append(f"«{c['name']}»: {len(uris)} canción(es) agregada(s) en Spotify")
                        elif c["type"] == "removed":
                            gone = set(c["paths"])
                            uris = sorted({f"spotify:track:{r['id']}" for r in (by_id.get(pid) or {}).get("tracks", [])
                                           if r.get("source") in gone and r.get("id")})
                            if uris:
                                sp.remove_from_library(uris) if is_liked else sp.remove_items(pid, uris)
                            refresh.add(pid)
                            done.append(f"«{c['name']}»: {len(uris)} canción(es) quitada(s) en Spotify")
                        elif c["type"] == "renamed" and not is_liked:
                            sp.rename_playlist(pid, c["name"])
                            refresh.add(pid)
                            done.append(f"«{c.get('old_name')}» ahora se llama «{c['name']}» en Spotify")
                        elif c["type"] == "deleted" and not is_liked:
                            sp.remove_from_library([f"spotify:playlist:{pid}"])
                            done.append(f"«{c['name']}»: quitada de tu biblioteca de Spotify")
                        accepted.add(c["rb_id"])
                except SpotifyError as e:
                    errors.append(f"«{c['name']}»: {e}")
            self._cfg["rb_keep"] = sorted(keep)
            config.save(self._cfg)
            rb_cambios.accept(state, [rid for rid in accepted], {**{rid: p for rid, p in new_pid.items()}})
            # volver a como está en la plataforma: se reescribe la playlist en Rekordbox ya mismo
            if revert:
                if rekordbox_sync.rekordbox_running():
                    self._cfg["rb_revert"] = sorted(set(self._cfg.get("rb_revert") or []) | revert)
                    config.save(self._cfg)
                    errors.append("Rekordbox está abierto: ciérralo y dale Organizar para devolver esas playlists a como están en la plataforma.")
                else:
                    target = [p for p in analysis if p["id"] in revert]
                    st = rekordbox_sync.sync(target, {**self._cfg, "rb_keep": []}, self._progress)
                    rb_cambios.merge_baseline(st.pop("baseline", None))
                    done.append(f"{len(target)} playlist(s) devuelta(s) en Rekordbox a como están en la plataforma")
            # traer de Spotify lo que cambió para que BrainOrder quede al día
            for pid in refresh:
                try:
                    meta = {"id": pid, "name": next((c["name"] for c in todo if c.get("pid") == pid or
                                                     new_pid.get(c["rb_id"]) == pid), pid), "source": "spotify"}
                    tracks = self._read_tracks(dict(meta))

                    def put(data, pid=pid, tracks=tracks, meta=meta):
                        cur = next((p for p in data["playlists"] if p["id"] == pid), None)
                        if cur is None:
                            cur = dict(meta)
                            data["playlists"].append(cur)
                        cur["tracks"] = tracks
                    self._update_sp(put)
                except Exception as e:
                    config.log(f"No pude releer {pid} de Spotify: {e!r}")
            analysis2 = self._build_analysis(light=True) if refresh else None
            return {"done": done, "errors": errors, "unresolved": unresolved, "analysis": analysis2,
                    "keep": self._cfg.get("rb_keep")}
        return self._task(run, "rb_apply", "Cambios de Rekordbox")

    # ---------- Mixed In Key -> programas de DJ ----------
    def _mik_targets(self, only=None):
        keys = [k for k in mik_dj.PROGRAMS if destinos.DESTINATIONS[k].enabled(self._cfg)]
        return [k for k in keys if not only or k in only]

    def mik_dj(self, apply=False, only=None):
        """Ver (apply=False, sin cerrar nada) o pasar ya key, energía y hot cues de MIK a cada programa activo."""
        def run():
            out = {}
            keys = self._mik_targets(only)
            for j, k in enumerate(keys):
                m = destinos.DESTINATIONS[k]
                self._sub_stage(j / len(keys), (j + 1) / len(keys))
                try:
                    res = mik_dj.run(self._cfg, k, apply=bool(apply), progress=self._progress)
                    sm = mik_dj.summary(res["changes"])
                    sm.update(label=m.LABEL, backup=res.get("backup"), serato_no_cues=res.get("serato_no_cues", 0))
                    out[k] = sm
                except Exception as e:
                    out[k] = {"label": m.LABEL, "error": str(e)}
            n = sum(v.get("count", 0) for v in out.values())
            self._progress(f"{n} cambios {'aplicados' if apply else 'pendientes'} de Mixed In Key.", 1)
            return {"programs": out, "applied": bool(apply), "none": not keys}
        return self._task(run, "mik_dj", "Mixed In Key → programas de DJ", files=bool(apply))

    def mik_rb(self, apply=False):  # compatibilidad
        return self.mik_dj(apply, ["rekordbox"])

    def _watch_mik(self):
        """Cada 5 min: a cada programa de DJ cerrado le pasa lo nuevo de MIK (con respaldo)."""
        import time
        time.sleep(60)
        while True:
            try:
                if self._cfg.get("rb_mik_auto", True) and not self._running:
                    done = {}
                    for k in self._mik_targets():
                        m = destinos.DESTINATIONS[k]
                        try:
                            # mirar no necesita turno (solo lee); escribir sí, y solo con el programa cerrado
                            if m.running() or not mik_dj.run(self._cfg, k, apply=False)["changes"]:
                                continue
                            if not self._files.acquire(blocking=False):
                                break  # hay otra tarea moviendo archivos: se reintenta en 5 min
                            try:
                                if m.running() or self._running:
                                    continue
                                # Rekordbox: como mucho un respaldo por hora en el automático (cada uno pesa ~200 MB)
                                bk = not (k == "rekordbox" and rekordbox_sync.recent_backup(60))
                                res = mik_dj.run(self._cfg, k, apply=True, backup=bk)
                            finally:
                                self._files.release()
                            sm = mik_dj.summary(res["changes"])
                            if sm["count"]:
                                done[k] = {"label": m.LABEL, "count": sm["count"], "cues": sm["cues"],
                                           "backup": res.get("backup")}
                        except Exception as e:
                            config.log(f"MIK -> {m.LABEL} automático: {e!r}")
                    if done and self._window:
                        self._window.evaluate_js(f"window.onMikDj && onMikDj({json.dumps(done)})")
            except Exception as e:
                config.log(f"MIK automático: {e!r}")
            time.sleep(300)

    def rb_unkeep(self, pid):
        """Vuelve a sincronizar esa playlist desde su plataforma (deja de mandar Rekordbox)."""
        self._cfg["rb_keep"] = [p for p in self._cfg.get("rb_keep") or [] if p != pid]
        config.save(self._cfg)
        return {"ok": True, "keep": self._cfg["rb_keep"]}

    # ---------- utilidades de UI ----------
    def reveal(self, path):
        plataforma.reveal(path)
        return {"ok": True}

    def open_url(self, url):
        plataforma.open_url(url)
        return {"ok": True}

    def copy_text(self, text):
        """Copia texto al portapapeles (Mac y Windows)."""
        ok = plataforma.copy_text(text or "")
        return {"ok": ok, "error": None if ok else "No pude copiar al portapapeles."}

    # ---------- actualizaciones ----------
    def check_updates(self):
        """Se llama al abrir la app: si hay versión nueva la descarga para el próximo inicio."""
        try:
            return actualizador.check_and_download()
        except Exception as e:
            config.log(f"check_updates: {e!r}")
            return {"status": "error"}

    def restart(self):
        """Cierra y vuelve a abrir BrainOrder (así se instala la actualización descargada)."""
        arr = config.SUPPORT_DIR / "arranque.py"
        bundle = os.environ.get("BRAINORDER_BUNDLE") or os.environ.get("SPOTISYNC_BUNDLE")
        try:
            if plataforma.IS_MAC and bundle and Path(bundle).exists():
                subprocess.Popen(["/bin/sh", "-c", f'sleep 1; open -n "{bundle}"'])
            elif arr.exists():
                kw = {}
                if plataforma.IS_WIN:
                    kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
                subprocess.Popen([sys.executable, str(arr)], **kw)
            else:
                return {"ok": False, "error": "No encuentro el arranque instalado. Ábrela de nuevo a mano."}
        except Exception as e:
            return {"ok": False, "error": f"No pude reiniciar: {e}"}
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return {"ok": True}

    def platform(self):
        return {"win": plataforma.IS_WIN, "mac": plataforma.IS_MAC}

    def export_excel(self):
        """Genera un Excel con las canciones que faltan (nombre, artista, Spotify, Deezer)."""
        try:
            import excel
        except ImportError:
            return {"ok": False, "error": "Falta un componente para Excel. Vuelve a abrir «Instalar BrainOrder» y listo."}
        from datetime import datetime
        analysis = self._analysis()
        if not analysis:
            return {"ok": False, "error": "Primero dale a Analizar."}
        name = f"BrainOrder faltantes {datetime.now():%Y-%m-%d}.xlsx"
        default_dir = self._cfg["inbox"] if Path(self._cfg["inbox"]).exists() else str(Path.home() / "Music")
        path = None
        try:
            import webview
            kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
            res = self._window.create_file_dialog(kind, directory=default_dir, save_filename=name)
            if not res:
                return {"ok": False, "cancelled": True}
            path = res[0] if isinstance(res, (list, tuple)) else str(res)
        except Exception as e:
            config.log(f"Diálogo de guardar falló ({e}); se guarda en descargas")
            path = str(Path(default_dir) / name)
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            n = excel.build(analysis, path)
        except Exception as e:
            config.log(traceback.format_exc())
            return {"ok": False, "error": f"No pude crear el Excel: {e}"}
        plataforma.open_path(path)
        return {"ok": True, "path": path, "count": n}


    # ---------- informes por playlist ----------
    def _reports_dir(self):
        d = Path(self._cfg["dest_root"]) / "_Informes"
        try:
            d.mkdir(parents=True, exist_ok=True)
            return str(d)
        except Exception:
            return str(Path.home() / "Music")

    def export_playlist_excel(self, index):
        """Informe Excel de UNA playlist (todas sus canciones con estado y links)."""
        try:
            import excel
        except ImportError:
            return {"ok": False, "error": "Falta un componente para Excel. Vuelve a abrir «Instalar BrainOrder»."}
        from datetime import datetime
        analysis = self._analysis() or []
        try:
            pl = analysis[int(index)]
        except Exception:
            return {"ok": False, "error": "No encontré esa playlist. Vuelve a Analizar."}
        name = f"{config.safe_name(pl['name'])} {datetime.now():%Y-%m-%d}.xlsx"
        default_dir = self._reports_dir()
        try:
            import webview
            kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
            res = self._window.create_file_dialog(kind, directory=default_dir, save_filename=name)
            if not res:
                return {"ok": False, "cancelled": True}
            path = res[0] if isinstance(res, (list, tuple)) else str(res)
        except Exception as e:
            config.log(f"Diálogo de guardar falló ({e}); se guarda en _Informes")
            path = str(Path(default_dir) / name)
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            info = excel.build_playlist(pl, path)
        except Exception as e:
            config.log(traceback.format_exc())
            return {"ok": False, "error": f"No pude crear el Excel: {e}"}
        plataforma.open_path(path)
        return {"ok": True, "path": path, **info}

    def export_all_playlists_excel(self):
        """Un Excel por cada playlist, todos en la carpeta que elijas."""
        try:
            import excel
        except ImportError:
            return {"ok": False, "error": "Falta un componente para Excel. Vuelve a abrir «Instalar BrainOrder»."}
        from datetime import datetime
        analysis = self._analysis() or []
        if not analysis:
            return {"ok": False, "error": "Primero dale a Analizar."}
        folder = self.pick_folder(self._reports_dir())
        if not folder:
            return {"ok": False, "cancelled": True}
        stamp = f"{datetime.now():%Y-%m-%d}"
        analysis = [p for p in analysis if p.get("tracks")]

        def run():
            done, errors = 0, []
            for i, pl in enumerate(analysis, 1):
                self._progress(f"Informe {i}/{len(analysis)}: {pl['name']}", i / len(analysis))
                try:
                    excel.build_playlist(pl, str(Path(folder) / f"{config.safe_name(pl['name'])} {stamp}.xlsx"))
                    done += 1
                except Exception as e:
                    errors.append(f"{pl['name']}: {e}")
                    config.log(f"Informe de {pl['name']} falló: {e}")
            plataforma.open_path(folder)
            return {"path": folder, "count": done, "errors": errors}
        return self._task(run, "export_all", "Informes Excel")


    # ---------- unificar repetidos ----------
    def unify_plan(self):
        """Revisa la carpeta espejo y propone qué unificar (no mueve nada)."""
        def run():
            analysis = self._analysis()
            pl = unificar.plan(self._cfg, analysis, self._progress)
            self._unify_plan = pl
            self._progress("Revisión lista. Nada se ha movido todavía.", 1)
            return {"plan": pl, "rekordbox_running": rekordbox_sync.rekordbox_running()}
        return self._task(run, "unify_plan", "Revisar repetidos")

    # ---------- duplicados físicos en toda la biblioteca ----------
    def dup_scan(self):
        def run():
            import duplicados
            analysis = self._analysis()
            self._set_stage(0, 15)
            rb = unificar.rb_index(self._progress) or {}
            self._set_stage(15, 100)
            res = duplicados.scan(self._cfg, analysis, rb, self._progress)
            self._dup_scan = res
            return {"scan": res, "rekordbox_running": rekordbox_sync.rekordbox_running()}
        return self._task(run, "dup_scan", "Buscar duplicados")

    def dup_apply(self, choices):
        """choices: {grupo: {keep, remove: [rutas]}}. Aparta en _duplicados (con Historial) y corrige programas de DJ."""
        def run():
            import duplicados
            scan = getattr(self, "_dup_scan", None)
            if not scan:
                raise unificar.UnifyError("Primero dale a Buscar duplicados.")
            plan = duplicados.to_unify_plan(scan, choices or {})
            if not plan["dups"]:
                raise unificar.UnifyError("No marcaste ningún archivo para apartar.")
            self._dj_precheck()
            with self._state:
                res = unificar.apply(plan, self._cfg, [], [g["id"] for g in plan["dups"]], False, self._progress)
                moved_map = res.pop("moved_map", {})
                res["dj"], res["dj_warnings"] = self._dj_fix(moved_map, res.pop("repoint", {}))
                res["op_id"] = historial.record("unify", "Apartar duplicados", list(moved_map.items()))
                analysis = None
                if any(p.get("tracks") is not None for p in self._load_sp()["playlists"]):
                    self._progress("Actualizando el análisis…")
                    analysis = self._build_analysis(light=True)
            done = {gid for gid in (choices or {})}
            scan["groups"] = [g for g in scan["groups"] if g["id"] not in done]
            self._progress("Duplicados apartados.", 1)
            return {"result": res, "analysis": analysis, "scan": scan}
        return self._task(run, "dup_apply", "Apartar duplicados", files=True)

    def unify_apply(self, merge_ids, dup_ids, remove_empty):
        def run():
            pl = getattr(self, "_unify_plan", None)
            if not pl:
                raise unificar.UnifyError("Primero dale a Revisar.")
            self._dj_precheck()
            with self._state:
                res = unificar.apply(pl, self._cfg, merge_ids or [], dup_ids or [], bool(remove_empty), self._progress)
                moved_map = res.pop("moved_map", {})
                res["dj"], res["dj_warnings"] = self._dj_fix(moved_map, res.pop("repoint", {}))
                res["op_id"] = historial.record("unify", "Unificar repetidos", list(moved_map.items()))
                self._unify_plan = None
                analysis = None
                if any(p.get("tracks") is not None for p in self._load_sp()["playlists"]):
                    self._progress("Actualizando el análisis…")
                    analysis = self._build_analysis(light=True)
                    reportes.write_reports(analysis, self._cfg)
            self._progress("Unificación terminada.", 1)
            return {"result": res, "analysis": analysis}
        return self._task(run, "unify_apply", "Unificar repetidos", files=True)

def main():
    # En Windows (pythonw) no hay consola: los errores van al log
    if sys.stdout is None or sys.stderr is None:
        try:
            config.SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            f = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stdout or f
            sys.stderr = sys.stderr or f
        except Exception:
            pass
    import webview
    plataforma.migrate_launcher(config.log)  # antes se llamaba SpotiSync: renombra el ícono
    plataforma.refresh_launcher(config.log)  # el lanzador de BrainOrder.app también se actualiza
    icon = HERE / "icon.png"
    plataforma.mac_branding("BrainOrder", icon)  # «BrainOrder» junto a la manzana, no «Python»
    api = Api()
    win = webview.create_window("BrainOrder", str(HERE / "ui.html"), js_api=api,
                                width=1280, height=820, min_size=(900, 600),
                                background_color="#0d0e12")
    api._window = win
    import inspect
    kw = {}
    try:
        if icon.exists() and "icon" in inspect.signature(webview.start).parameters:
            kw["icon"] = str(icon)
    except (TypeError, ValueError):
        pass
    webview.start(**kw)


if __name__ == "__main__":
    main()
