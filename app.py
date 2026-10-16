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

    def _progress(self, msg):
        config.log(msg)
        if self._window:
            try:
                self._window.evaluate_js(f"window.onProgress && onProgress({json.dumps(msg)})")
            except Exception:
                pass

    def _wrap(self, fn, *a):
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "Ya hay una tarea en curso, espera a que termine."}
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
    def _build_analysis(self, sp_data):
        playlists = list(sp_data["playlists"])
        if self._cfg.get("include_liked") and sp_data.get("liked") is not None:
            playlists.append({"id": "liked", "name": self._cfg.get("liked_name", "Me gusta"),
                              "tracks": sp_data["liked"], "liked": True})
        for fp in sp_data.get("foreign_ok", []):
            playlists.append(fp)
        analysis = biblioteca.analyze(playlists, self._cfg, self._progress)
        deezer.add_links(analysis, self._progress)
        self._progress("Escribiendo listas de faltantes en cada carpeta…")
        reportes.write_reports(analysis, self._cfg)
        for pl in analysis:
            txt = Path(pl["folder"]) / reportes.TXT_NAME
            pl["report"] = str(txt) if txt.exists() else None
        _write_json(CACHE_ANALYSIS, analysis)
        return analysis

    def analyze(self):
        def run():
            sp = self._sp()
            playlists = sp.my_playlists(self._progress)
            liked = sp.liked(self._progress) if self._cfg.get("include_liked") else None

            # playlists ajenas: registrar nuevas y leer las que elegiste integrar
            known = self._cfg.setdefault("foreign", {})
            new = []
            for f in sp.foreign:
                if f["id"] not in known:
                    known[f["id"]] = {**f, "choice": "preguntar"}
                    new.append(f["id"])
                else:
                    known[f["id"]].update(name=f["name"], owner=f["owner"], url=f["url"])
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

            sp_data = {"playlists": playlists, "liked": liked, "foreign_ok": foreign_ok}
            _write_json(CACHE_SPOTIFY, sp_data)
            analysis = self._build_analysis(sp_data)
            self._progress("Análisis listo.")
            return {"analysis": analysis, "foreign": known,
                    "ask_foreign": [pid for pid, f in known.items() if f.get("choice") == "preguntar"]}
        return self._wrap(run)

    # ---------- organizar ----------
    def organize(self, include_rekordbox=True):
        def run():
            sp_data = _read_json(CACHE_SPOTIFY, None)
            analysis = _read_json(CACHE_ANALYSIS, None)
            if not sp_data or not analysis:
                raise SpotifyError("Primero dale a Analizar.")
            files = organizador.organize(analysis, self._cfg, self._progress)
            self._progress("Re-escaneando tu música…")
            analysis = self._build_analysis(sp_data)
            rb, rb_error = None, None
            if include_rekordbox:
                try:
                    rb = rekordbox_sync.sync(analysis, self._cfg, self._progress)
                except rekordbox_sync.RekordboxError as e:
                    rb_error = str(e)
            self._progress("Organización terminada.")
            return {"files": files, "rekordbox": rb, "rekordbox_error": rb_error, "analysis": analysis}
        return self._wrap(run, )

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
            sp_data = _read_json(CACHE_SPOTIFY, None)
            if sp_data:
                self._progress("Actualizando el análisis…")
                analysis = self._build_analysis(sp_data)
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
