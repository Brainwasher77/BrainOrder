"""SpotiSync — Spotify ↔ archivos locales ↔ Rekordbox.

Ventana nativa de macOS (pywebview). Ejecutar: python app.py
"""
import csv
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
import organizador  # noqa: E402
import plataforma  # noqa: E402
import rekordbox_sync  # noqa: E402
import reportes  # noqa: E402
import deezer  # noqa: E402
import unificar  # noqa: E402
import actualizador  # noqa: E402
from spotify_api import Spotify, SpotifyError  # noqa: E402

CACHE_SPOTIFY = config.SUPPORT_DIR / "spotify_cache.json"
CACHE_ANALYSIS = config.SUPPORT_DIR / "analysis_cache.json"


def _read_json(p, default):
    try:
        return json.loads(Path(p).read_text("utf-8"))
    except Exception:
        return default


def _write_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, ensure_ascii=False), "utf-8")


class Api:
    def __init__(self):
        self._window = None
        self._cfg = config.load()
        biblioteca.load_durations(config.SUPPORT_DIR / "durations.json")
        self._lock = threading.Lock()

    # ---------- utilidades ----------
    def _sp(self):
        return Spotify(self._cfg.get("client_id", ""), self._cfg["redirect_uri"])

    # Progreso: cada etapa ocupa un tramo [lo, hi] de 0-100 %; las funciones informan su avance
    # dentro de la etapa (0..1) y aquí se convierte al porcentaje total.
    _stage = (0.0, 100.0)
    _last_pct = None

    def _set_stage(self, lo, hi, send=True):
        self._stage = (float(lo), float(hi))
        if send:
            self._send(None, lo)

    def _progress(self, msg, frac=None):
        lo, hi = self._stage
        pct = None if frac is None else lo + (hi - lo) * max(0.0, min(1.0, float(frac)))
        if msg:
            config.log(msg)
        self._send(msg, pct)

    def _send(self, msg, pct):
        if pct is not None:
            pct = round(pct)
            if pct == self._last_pct and msg is None:
                return
            self._last_pct = pct
        if self._window:
            try:
                self._window.evaluate_js(f"window.onProgress && onProgress({json.dumps(msg)}, {json.dumps(pct)})")
            except Exception:
                pass

    def _wrap(self, fn, *a):
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "Ya hay una tarea en curso, espera a que termine."}
        self._stage, self._last_pct = (0.0, 100.0), None
        try:
            return {"ok": True, **(fn(*a) or {})}
        except (SpotifyError, rekordbox_sync.RekordboxError, unificar.UnifyError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            config.log(traceback.format_exc())
            return {"ok": False, "error": f"Error inesperado: {e}"}
        finally:
            self._lock.release()

    # ---------- estado ----------
    def get_state(self):
        sp = self._sp()
        return {
            "connected": sp.connected,
            "settings": {k: self._cfg[k] for k in ("client_id", "redirect_uri", "dest_root", "inbox",
                                                   "library_roots", "liked_name", "include_liked",
                                                   "rekordbox_folder")},
            "analysis": _read_json(CACHE_ANALYSIS, None),
            "foreign": self._cfg.get("foreign", {}),
            "rekordbox_running": rekordbox_sync.rekordbox_running(),
            "home": str(Path.home()),
            "pinned": self._cfg.get("pinned_paths", []),
            "inbox_count": self._inbox_signature()[1],
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

    def save_settings(self, s):
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
        return {"ok": True}

    # ---------- Spotify ----------
    def connect(self):
        def run():
            me = self._sp().login()
            return {"user": me.get("display_name") or me.get("id")}
        return self._wrap(run)

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
        try:
            total = sp.get("/me/tracks", {"limit": 1}).get("total", 0)
        except SpotifyError:
            total = None
        return {"id": "liked", "name": self._cfg.get("liked_name", "Me gusta"), "liked": True,
                "snapshot": f"n{total}" if total is not None else None, "total": total}

    def _register_foreign(self, sp):
        known = self._cfg.setdefault("foreign", {})
        for f in sp.foreign:
            if f["id"] not in known:
                known[f["id"]] = {**f, "choice": "preguntar"}
            else:
                known[f["id"]].update(name=f["name"], owner=f["owner"], url=f["url"])
        config.save(self._cfg)
        return known

    def _build_analysis(self, sp_data, focus=None, light=False, quiet=False):
        """Cruza la caché de Spotify con tus archivos.
        focus: ids de playlists a las que se les buscan links de Deezer y se les escribe el .txt
               (None = todas). light=True: solo cruce local, sin Deezer ni .txt (rápido)."""
        include_liked = self._cfg.get("include_liked")
        meta = {p["id"]: p for p in sp_data["playlists"]}
        loaded = [p for p in sp_data["playlists"]
                  if p.get("tracks") is not None and (include_liked or p["id"] != "liked")]
        loaded = [{**p, "name": self._cfg.get("liked_name", "Me gusta") if p["id"] == "liked" else p["name"]}
                  for p in loaded] + list(sp_data.get("foreign_ok", []))
        staged = not quiet and not light
        if staged:
            self._set_stage(self._stage[0], self._stage[0] + (self._stage[1] - self._stage[0]) * 0.45)
        result = biblioteca.analyze(loaded, self._cfg, None if quiet else self._progress)
        if staged:
            self._set_stage(self._stage[1], 97)
        by_id = {a["id"]: a for a in result}

        if light:
            deezer.add_links(result, offline=True)
        elif focus:
            sel = [a for a in result if a["id"] in focus]
            deezer.add_links(sel, self._progress)
            self._set_stage(97, 100)
            deezer.add_links([a for a in result if a["id"] not in focus], offline=True)
            self._progress("Escribiendo la lista de faltantes en la carpeta…")
            reportes.write_reports(sel, self._cfg)
        else:
            deezer.add_links(result, self._progress)
            self._set_stage(97, 100)
            self._progress("Escribiendo listas de faltantes en cada carpeta…")
            reportes.write_reports(result, self._cfg)

        analysis = []
        for p in sp_data["playlists"]:
            if p["id"] == "liked" and not include_liked:
                continue
            a = by_id.get(p["id"])
            if a is None:  # todavía sin analizar
                name = self._cfg.get("liked_name", "Me gusta") if p["id"] == "liked" else p["name"]
                a = {"id": p["id"], "name": name, "tracks": [], "pending": True, "liked": p["id"] == "liked",
                     "folder": str(biblioteca.resolve_folder(Path(self._cfg["dest_root"]), name))}
            a["snapshot"] = p.get("snapshot")
            a["analyzed_snapshot"] = p.get("analyzed_snapshot")
            a["total"] = p.get("total")
            analysis.append(a)
        analysis += [a for a in result if a["id"] not in meta]  # playlists ajenas integradas
        for pl in analysis:
            txt = Path(pl["folder"]) / reportes.TXT_NAME
            pl["report"] = str(txt) if txt.exists() else None
        _write_json(CACHE_ANALYSIS, analysis)
        return analysis

    # ---------- analizar ----------
    def list_playlists(self):
        """Trae solo la lista de tus playlists (sin canciones). Rápido."""
        def run():
            sp = self._sp()
            self._progress("Leyendo la lista de tus playlists…")
            own = sp.list_mine()
            data = self._load_sp()
            old = {p["id"]: p for p in data["playlists"]}
            new = []
            for m in own + ([self._liked_meta(sp)] if self._cfg.get("include_liked") else []):
                o = old.get(m["id"]) or {}
                new.append({**m, "tracks": o.get("tracks"), "analyzed_snapshot": o.get("analyzed_snapshot")})
            data["playlists"] = new
            known = self._register_foreign(sp)
            _write_json(CACHE_SPOTIFY, data)
            analysis = self._build_analysis(data, light=True)
            self._progress(f"{len(own)} playlists. Elige una y dale Analizar, o Analizar todo.")
            return {"analysis": analysis, "foreign": known,
                    "ask_foreign": [pid for pid, f in known.items() if f.get("choice") == "preguntar"]}
        return self._wrap(run)

    def analyze_playlist(self, pid):
        """Lee de Spotify SOLO esta playlist y la cruza con tus archivos."""
        def run():
            sp = self._sp()
            data = self._load_sp()
            entry = next((p for p in data["playlists"] if p["id"] == pid), None)
            if entry is None:
                raise SpotifyError("No encontré esa playlist. Dale a ⟳ para recargar la lista.")
            self._set_stage(0, 40)
            self._progress(f"Leyendo «{entry['name']}» de Spotify…", 0)
            if pid == "liked":
                entry.update(self._liked_meta(sp))
                entry["tracks"] = sp.liked(self._progress)
            else:
                entry["tracks"] = sp.playlist_tracks(pid, self._progress, entry.get("total"))
            self._set_stage(40, 100)
            entry["analyzed_snapshot"] = entry.get("snapshot")
            _write_json(CACHE_SPOTIFY, data)
            analysis = self._build_analysis(data, focus={pid})
            self._progress(f"«{entry['name']}» analizada.", 1)
            self._set_stage(0, 100, send=False)
            return {"analysis": analysis}
        return self._wrap(run)

    def analyze(self):
        """Analizar todo: todas tus playlists y Me gusta."""
        def run():
            sp = self._sp()
            self._set_stage(0, 45)
            playlists = sp.my_playlists(self._progress)
            for p in playlists:
                p["analyzed_snapshot"] = p.get("snapshot")
            if self._cfg.get("include_liked"):
                lm = self._liked_meta(sp)
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
            sp_data = {"playlists": playlists, "foreign_ok": foreign_ok}
            _write_json(CACHE_SPOTIFY, sp_data)
            self._set_stage(45, 100)
            analysis = self._build_analysis(sp_data)
            self._progress("Análisis listo.", 1)
            self._set_stage(0, 100, send=False)
            return {"analysis": analysis, "foreign": known,
                    "ask_foreign": [pid for pid, f in known.items() if f.get("choice") == "preguntar"]}
        return self._wrap(run)

    # ---------- organizar ----------
    def organize(self, include_rekordbox=True, pid=None, extra=None):
        """Organiza todo, o solo una playlist (pid).
        extra (solo en el general): {"groups": [nombres de subcarpetas de descargas],
                                     "files": [{"src", "dest"}]} para descargas sin playlist."""
        def run():
            sp_data = self._load_sp()
            analysis = _read_json(CACHE_ANALYSIS, None) or []
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
            if not sp_data["playlists"] or not analysis:
                self._inbox_sig = None
                return {"files": files, "extra": extra_res, "rekordbox": None, "rekordbox_error": None,
                        "analysis": analysis or None}
            self._progress("Re-escaneando tu música…")
            analysis = self._build_analysis(sp_data, focus={pid} if pid else None)
            rb, rb_error = None, None
            if include_rekordbox:
                try:
                    target = [p for p in analysis if p["id"] == pid] if pid else analysis
                    rb = rekordbox_sync.sync(target, self._cfg, self._progress)
                except rekordbox_sync.RekordboxError as e:
                    rb_error = str(e)
            self._inbox_sig = None  # forzar que el vigilante vuelva a mirar descargas
            self._progress("Organización terminada.")
            return {"files": files, "extra": extra_res, "rekordbox": rb, "rekordbox_error": rb_error,
                    "analysis": analysis}
        return self._wrap(run)

    # ---------- reorganizar por playlist ----------
    def relocate(self, pid, moves, keep, remember=True):
        """moves: [{src, dest}] archivos a mover; keep: rutas que se dejan donde están."""
        def run():
            analysis = _read_json(CACHE_ANALYSIS, None) or []
            pl = next((p for p in analysis if p["id"] == pid), None)
            if not pl:
                raise SpotifyError("No encontré esa playlist. Vuelve a analizarla.")
            valid_src = {r["source"] for r in pl["tracks"] if r.get("source") and r["status"] in ("ok", "elsewhere")}
            allowed = {a["folder"] for a in analysis} | {r["dest_dir"] for r in pl["tracks"] if r.get("dest_dir")}
            ops, seen = [], set()
            for m in moves or []:
                src, dest = m.get("src"), m.get("dest")
                if src in valid_src and dest in allowed and src not in seen and str(Path(src).parent) != dest:
                    ops.append((src, dest))
                    seen.add(src)
            res = organizador.relocate(ops, self._cfg, self._progress) if ops else \
                {"moved": 0, "skipped": [], "rekordbox": None, "backup": None, "changes": {}}
            pinned = set(self._cfg.get("pinned_paths", []))
            if remember:
                pinned |= {p for p in (keep or []) if p in valid_src}
                # lo que moviste a una carpeta que no es "su" carpeta también queda fijado
                home = {r["source"]: r.get("dest_dir") for r in pl["tracks"] if r.get("source")}
                for src, new in res["changes"].items():
                    if str(Path(new).parent) != home.get(src):
                        pinned.add(new)
            pinned -= set(res["changes"])  # las rutas viejas ya no existen
            self._cfg["pinned_paths"] = sorted(pinned)
            config.save(self._cfg)
            data = self._load_sp()
            analysis = self._build_analysis(data, focus={pid})
            res.pop("changes", None)
            return {"result": res, "analysis": analysis, "pinned": self._cfg["pinned_paths"]}
        return self._wrap(run)

    def unpin(self, paths):
        self._cfg["pinned_paths"] = sorted(set(self._cfg.get("pinned_paths", [])) - set(paths or []))
        config.save(self._cfg)
        return {"ok": True, "pinned": self._cfg["pinned_paths"]}

    def inbox_status(self):
        """Qué hay en descargas: listos para su playlist, repetidos y sin playlist (por subcarpeta)."""
        sig, n = self._inbox_signature()
        files = [p for p, _, _ in sig]
        analysis = _read_json(CACHE_ANALYSIS, None) or []
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
                "pending": sum(1 for p in analysis if p.get("pending"))}

    # ---------- vigilante de la carpeta de descargas ----------
    def _inbox_signature(self):
        inbox = Path(self._cfg["inbox"])
        skip = {self._cfg.get("inbox_done", "_organizadas"), "_duplicados"}
        sig = []
        if not inbox.is_dir():
            return (), 0
        for dirpath, dirnames, filenames in os.walk(inbox):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip]
            for fn in filenames:
                if fn.startswith(".") or Path(fn).suffix.lower() not in config.AUDIO_EXT:
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
        last_seen, stable = None, 0
        while True:
            time.sleep(4)
            try:
                sig, n = self._inbox_signature()
                if sig != last_seen:          # algo cambió: esperar a que deje de cambiar (descarga en curso)
                    last_seen, stable = sig, 0
                    continue
                stable += 1
                if sig == self._inbox_sig or stable < 1:
                    continue
                prev = set(p for p, _, _ in (self._inbox_sig or ()))
                nuevos = [p for p, _, _ in sig if p not in prev] if self._inbox_sig is not None else []
                if not self._lock.acquire(blocking=False):
                    continue  # hay otra tarea en curso; se reintenta
                try:
                    self._inbox_sig = sig
                    data = self._load_sp()
                    if any(p.get("tracks") is not None for p in data["playlists"]):
                        self._build_analysis(data, light=True, quiet=True)
                finally:
                    self._lock.release()
                if self._window:
                    payload = json.dumps({"count": n, "new": [Path(p).name for p in nuevos][:20],
                                          "new_count": len(nuevos)})
                    self._window.evaluate_js(f"window.onInboxChange && onInboxChange({payload})")
            except Exception as e:
                config.log(f"vigilante de descargas: {e!r}")

    def start_watch(self):
        if getattr(self, "_watching", False):
            return {"ok": True}
        self._watching = True
        threading.Thread(target=self._watch_inbox, daemon=True).start()
        return {"ok": True}

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
        """Cierra y vuelve a abrir SpotiSync (así se instala la actualización descargada)."""
        arr = config.SUPPORT_DIR / "arranque.py"
        bundle = os.environ.get("SPOTISYNC_BUNDLE")
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
            return {"ok": False, "error": "Falta un componente para Excel. Vuelve a abrir 'Instalar SpotiSync.command' y listo."}
        from datetime import datetime
        analysis = _read_json(CACHE_ANALYSIS, None)
        if not analysis:
            return {"ok": False, "error": "Primero dale a Analizar."}
        name = f"SpotiSync faltantes {datetime.now():%Y-%m-%d}.xlsx"
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
            return {"ok": False, "error": "Falta un componente para Excel. Vuelve a abrir 'Instalar SpotiSync.command'."}
        from datetime import datetime
        analysis = _read_json(CACHE_ANALYSIS, None) or []
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
            return {"ok": False, "error": "Falta un componente para Excel. Vuelve a abrir 'Instalar SpotiSync.command'."}
        from datetime import datetime
        analysis = _read_json(CACHE_ANALYSIS, None) or []
        if not analysis:
            return {"ok": False, "error": "Primero dale a Analizar."}
        folder = self.pick_folder(self._reports_dir())
        if not folder:
            return {"ok": False, "cancelled": True}
        stamp = f"{datetime.now():%Y-%m-%d}"
        done, errors = 0, []
        analysis = [p for p in analysis if p.get("tracks")]
        for i, pl in enumerate(analysis, 1):
            self._progress(f"Informe {i}/{len(analysis)}: {pl['name']}")
            try:
                excel.build_playlist(pl, str(Path(folder) / f"{config.safe_name(pl['name'])} {stamp}.xlsx"))
                done += 1
            except Exception as e:
                errors.append(f"{pl['name']}: {e}")
                config.log(f"Informe de {pl['name']} falló: {e}")
        self._progress("Informes listos.")
        plataforma.open_path(folder)
        return {"ok": True, "path": folder, "count": done, "errors": errors}


    # ---------- unificar repetidos ----------
    def unify_plan(self):
        """Revisa la carpeta espejo y propone qué unificar (no mueve nada)."""
        def run():
            analysis = _read_json(CACHE_ANALYSIS, None)
            pl = unificar.plan(self._cfg, analysis, self._progress)
            self._unify_plan = pl
            self._progress("Revisión lista. Nada se ha movido todavía.")
            return {"plan": pl, "rekordbox_running": rekordbox_sync.rekordbox_running()}
        return self._wrap(run)

    def unify_apply(self, merge_ids, dup_ids, remove_empty):
        def run():
            pl = getattr(self, "_unify_plan", None)
            if not pl:
                raise unificar.UnifyError("Primero dale a Revisar.")
            res = unificar.apply(pl, self._cfg, merge_ids or [], dup_ids or [], bool(remove_empty), self._progress)
            self._unify_plan = None
            analysis = None
            sp_data = self._load_sp()
            if any(p.get("tracks") is not None for p in sp_data["playlists"]):
                self._progress("Actualizando el análisis…")
                analysis = self._build_analysis(sp_data, light=True)
                reportes.write_reports(analysis, self._cfg)
            self._progress("Unificación terminada.")
            return {"result": res, "analysis": analysis}
        return self._wrap(run)

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
    api = Api()
    win = webview.create_window("SpotiSync", str(HERE / "ui.html"), js_api=api,
                                width=1280, height=820, min_size=(900, 600),
                                background_color="#0d0e12")
    api._window = win
    webview.start()


if __name__ == "__main__":
    main()
