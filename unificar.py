"""Unificar repetidos dentro de la carpeta espejo de Spotify.

Tres cosas:
  1. Carpetas repetidas: misma playlist escrita distinto ("Stay High" / "Stay High🌒",
     "Clasica" / "Clásica"…). Se juntan en la que más música tiene.
  2. Canciones repetidas: misma canción (artista + título + versión) con la misma duración
     en varias carpetas. Se deja UNA y las demás van a  <Spotify playlists>/_duplicados/.
  3. Carpetas vacías: se eliminan (solo si no tienen ningún archivo).

Nunca se borra música: lo repetido se aparta en _duplicados.
Rekordbox: las pistas movidas se re-apuntan a su nueva ruta y las playlists que usaban una
copia repetida pasan a usar la copia que se conserva (sin perder cues). Si algo falla, se
deshacen los movimientos y Rekordbox queda como estaba.
"""
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import biblioteca as b
import reglas
from config import AUDIO_EXT, log
from plataforma import free_name, identical, is_dup_dir, native, rb_path, safe_move, same_file

DUP_DIR = "_duplicados"
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}
OUR_FILES = {"_FALTAN EN ESTA CARPETA.txt"}


class UnifyError(Exception):
    pass


# ---------------------------------------------------------------- Rekordbox (lectura)
def _real(path):
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino) if st.st_ino else os.path.normcase(os.path.realpath(path))
    except OSError:
        return os.path.normcase(os.path.realpath(path))


def _pkey(p):
    """Clave para comparar una ruta de BrainOrder con una de Rekordbox: mismas barras y, en Windows,
    sin distinguir mayúsculas (C:/Users/Frank y c:\\users\\frank son el mismo archivo)."""
    return os.path.normcase(native(str(p)))


def _with_links(paths):
    """Las rutas y, para las que son un acceso directo (alias / symlink), también el archivo al que
    apuntan: mover ese archivo también obliga a corregir Rekordbox."""
    for x in paths:
        yield x
        try:
            n = native(str(x))
            if os.path.islink(n):
                yield os.path.realpath(n)
        except (OSError, ValueError):
            pass


class RbSet(set):
    """Rutas de la librería de Rekordbox (y destinos de sus accesos directos); «ruta in rb» compara con _pkey."""
    def __init__(self, items=()):
        super().__init__(_pkey(x) for x in _with_links(items))

    def __contains__(self, p):
        return super().__contains__(_pkey(p))


class RbIndex(dict):
    """{ruta: info} de Rekordbox; get / in comparan con _pkey. Un acceso directo cuenta también para el
    archivo al que apunta (si ese archivo no tiene entrada propia)."""
    def __init__(self, items=()):
        items = dict(items)
        super().__init__((_pkey(k), v) for k, v in items.items())
        for k, v in items.items():
            try:
                n = native(str(k))
                if os.path.islink(n):
                    self.setdefault(_pkey(os.path.realpath(n)), v)
            except (OSError, ValueError):
                pass

    def __contains__(self, p):
        return super().__contains__(_pkey(p))

    def get(self, p, default=None):
        return super().get(_pkey(p), default)

    def __getitem__(self, p):
        return super().__getitem__(_pkey(p))


def rb_paths(progress=None):
    """Rutas de las pistas de tu librería de Rekordbox (solo lectura, rápido: una consulta directa).
    Sirve para saber si hay que corregir rutas allá al mover archivos. None si no se puede leer."""
    try:
        import rekordbox_sync
        if not (rekordbox_sync.RB_DIR / "master.db").exists():
            return None
        if progress:
            progress("Revisando tu librería de Rekordbox…")
        con = rekordbox_sync.connect_ro()
        try:
            return RbSet(r[0] for r in con.execute(
                "SELECT FolderPath FROM djmdContent WHERE COALESCE(rb_local_deleted, 0) = 0 AND FolderPath IS NOT NULL"))
        finally:
            con.close()
    except Exception as e:
        log(f"Rekordbox: lectura rápida falló ({e!r}); uso la completa")
        idx = rb_index(progress)
        return RbSet(idx) if idx is not None else None


def rb_index(progress=None):
    """{ruta: {"id", "playlists", "cues"}} de la librería de Rekordbox (solo lectura)."""
    try:
        try:
            from pyrekordbox import MasterDatabase as DB
        except ImportError:
            from pyrekordbox import Rekordbox6Database as DB
        import rekordbox_sync
        path = rekordbox_sync.RB_DIR / "master.db"
        if not path.exists():
            return None
        if progress:
            progress("Leyendo tu librería de Rekordbox…")
        db = DB(path=path)
    except Exception as e:
        log(f"Unificar: no pude leer Rekordbox ({e})")
        return None
    try:
        pls = defaultdict(int)
        for s in db.get_playlist_songs():
            pls[s.ContentID] += 1
        cues = defaultdict(int)
        for q in db.get_cue():
            cues[q.ContentID] += 1
        out = {}
        for c in db.get_content():
            if c.FolderPath:
                out[native(c.FolderPath)] = {"id": c.ID, "playlists": pls.get(c.ID, 0), "cues": cues.get(c.ID, 0)}
        return RbIndex(out)
    finally:
        try:
            db.close()
        except Exception:
            pass


# ---------------------------------------------------------------- plan
def _q(path):
    return reglas.quality(path, b._RULES[0])


def _mik(path):
    try:
        import armonia
        return bool(armonia.info(path).get("mik"))
    except Exception:
        return False


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def plan(cfg, analysis=None, progress=None):
    dest = Path(cfg["dest_root"])
    if not dest.exists():
        raise UnifyError(f"No existe la carpeta {dest}")
    rb = rb_index(progress) or {}

    # --- 1. carpetas repetidas
    if progress:
        progress("Buscando carpetas repetidas…")
    ex = reglas.Excluder(b.configure(cfg))
    subdirs = sorted(d for d in dest.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))
                     and not ex.dir_excluded(str(d)))
    counts = {str(d): b._audio_count(d) for d in subdirs}
    groups, used = [], set()
    for d in subdirs:
        if str(d) in used:
            continue
        g = [x for x in subdirs if str(x) not in used and b.similar_folders(d.name, x.name)]
        if len(g) > 1:
            used.update(str(x) for x in g)
            groups.append(g)
    merges = []
    for i, g in enumerate(groups):
        target = max(g, key=lambda x: (counts[str(x)], -len(x.name)))
        srcs = [x for x in g if x != target]
        moving = sum(counts[str(x)] for x in srcs)
        merges.append({
            "id": f"m{i}",
            "target": str(target),
            "target_audio": counts[str(target)],
            "sources": [{"folder": str(x), "audio": counts[str(x)]} for x in srcs],
            "moving": moving,
        })
    merge_src = {s["folder"]: m["target"] for m in merges for s in m["sources"]}

    # --- 2. canciones repetidas
    if progress:
        progress("Buscando canciones repetidas…")
    skip = str(dest / DUP_DIR) + os.sep, str(dest / "_Informes") + os.sep
    files = [f for f in b.scan([dest], excluder=ex) if not f.path.startswith(skip)]
    home = {}
    for pl in analysis or []:
        for r in pl["tracks"]:
            if r.get("source"):
                home.setdefault(r["source"], r.get("dest_dir"))

    def akey(f):
        return f.artist_n.split(" and ")[0].split(",")[0].strip()

    by_song = defaultdict(list)
    for f in files:
        if f.core and akey(f) not in b.UNKNOWN_ARTISTS:
            by_song[(akey(f), f.core, f.extras)].append(f)

    dups = []
    cand = [g for g in by_song.values() if len(g) > 1]
    for n, g in enumerate(cand, 1):
        if progress and n % 25 == 0:
            progress(f"Comparando duraciones {n}/{len(cand)}…")
        # sub-grupos por duración (misma grabación)
        subs = []
        for f in sorted(g, key=lambda x: b.duration(x.path) or 0):
            d = b.duration(f.path)
            for s in subs:
                if b.same_length(s[0][1], d):
                    s.append((f, d))
                    break
            else:
                subs.append([(f, d)])
        for s in subs:
            uniq = {}
            for f, d in s:  # el mismo archivo por dos caminos (acceso directo) no es un repetido
                uniq.setdefault(_real(f.path), (f, d))
            s = list(uniq.values())
            if len(s) < 2:
                continue
            members = [f for f, _ in s]

            def score(f):
                info = rb.get(f.path) or {}
                hd = home.get(f.path)
                # la copia analizada con Mixed In Key se conserva: MIK no vuelve a escribir en la otra
                # (la reconoce de su colección y la muestra como ya analizada)
                return (-info.get("cues", 0), -_mik(f.path), -info.get("playlists", 0), -(f.path in rb),
                        -(hd is not None and f.dir == hd), f.dir in merge_src, _q(f.path), -_size(f.path))

            members.sort(key=score)
            keep, rest = members[0], members[1:]
            kinfo = rb.get(keep.path)
            if kinfo and kinfo.get("cues"):
                why = "tiene cues en Rekordbox"
            elif _mik(keep.path) and not all(_mik(x.path) for x in rest):
                why = "está analizada con Mixed In Key"
            elif kinfo and kinfo.get("playlists"):
                why = f"está en {kinfo['playlists']} playlist(s) de Rekordbox"
            elif kinfo:
                why = "está en tu colección de Rekordbox"
            elif home.get(keep.path) == keep.dir:
                why = "está en la carpeta de su playlist"
            elif keep.dir in merge_src:
                why = "mejor calidad"
            else:
                why = "mejor calidad / archivo más grande"
            dups.append({
                "id": f"d{len(dups)}",
                "song": f"{keep.artist} - {keep.title}",
                "keep": keep.path,
                "why": why,
                "remove": [f.path for f in rest],
                "seconds": s[0][1],
                "rb": any(f.path in rb for f in members),
            })
    b.save_durations()

    # --- 3. carpetas vacías: sin música ni otros archivos tuyos (.DS_Store no cuenta).
    # Las carpetas de playlists actuales se respetan aunque estén vacías: ahí vive su lista de
    # faltantes y ahí caerán sus descargas. Solo se proponen las que ya no son de ninguna playlist.
    current = {pl["folder"] for pl in (analysis or [])}
    empty = []
    for d in subdirs:
        if str(d) in merge_src or str(d) in current:
            continue  # las repetidas se borran solas al juntarlas
        try:
            names = [e.name for e in os.scandir(d)]
        except OSError:
            continue
        allowed = JUNK | OUR_FILES if analysis else JUNK
        if all(n in allowed for n in names):
            empty.append(str(d))

    affected = {p for g in dups for p in g["remove"]} | {
        str(Path(s["folder"]) / f.name)
        for m in merges for s in m["sources"]
        for f in (os.scandir(s["folder"]) if os.path.isdir(s["folder"]) else [])
        if f.is_file()}
    return {
        "dest": str(dest),
        "merges": merges,
        "dups": dups,
        "empty": empty,
        "rb_read": bool(rb),
        "rb_affected": sum(1 for p in affected if p in rb),
        "bytes": sum(_size(p) for g in dups for p in g["remove"]),
        "created": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- aplicar
def _unique(dst: Path) -> Path:
    if not dst.exists():
        return dst
    i = 2
    while True:
        c = dst.with_name(f"{dst.stem} ({i}){dst.suffix}")
        if not c.exists():
            return c
        i += 1


def apply(pl, cfg, merge_ids, dup_ids, remove_empty, progress=None):
    import rekordbox_sync

    dest = Path(pl["dest"])
    dupdir = dest / DUP_DIR
    merges = [m for m in pl["merges"] if m["id"] in set(merge_ids)]
    dups = [g for g in pl["dups"] if g["id"] in set(dup_ids)]

    rb = rb_index(progress) or {}
    touched = {p for g in dups for p in g["remove"]}
    for m in merges:
        for s in m["sources"]:
            if os.path.isdir(s["folder"]):
                touched |= {str(Path(s["folder"]) / e.name) for e in os.scandir(s["folder"]) if e.is_file()}
    need_rb = any(p in rb for p in touched)
    if need_rb and rekordbox_sync.rekordbox_running():
        raise UnifyError("Rekordbox está abierto. Ciérralo y vuelve a darle a Unificar "
                         "(hay que corregir rutas de pistas que están en tu librería).")
    backup = rekordbox_sync.backup().name if need_rb else None

    moves = []          # (origen, destino) para deshacer
    path_change = {}    # archivo que sigue activo pero cambió de carpeta
    retired = {}        # copia repetida -> dónde quedó en _duplicados
    dup_of = {}         # copia repetida -> archivo que se conserva
    log_lines = []

    def move(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        safe_move(str(src), str(dst))
        moves.append((str(src), str(dst)))

    def retire(src: Path, keeper: str):
        """Aparta src SOLO si de verdad hay otra copia: keeper existe, no está en _duplicados y no es el
        mismo archivo por otro camino. Si no, src se queda donde está (antes podía apartarse la única copia)."""
        if not keeper or not os.path.exists(keeper) or is_dup_dir(keeper) or same_file(src, keeper):
            log_lines.append(f"SE QUEDA  {src}\n          (no hay otra copia segura: no se aparta)")
            return False
        dst = _unique(dupdir / src.parent.name / src.name)
        move(src, dst)
        retired[str(src)] = str(dst)
        dup_of[str(src)] = keeper
        log_lines.append(f"REPETIDA  {src}\n          se conserva: {keeper}\n          apartada en: {dst}")
        return True

    try:
        # 2. canciones repetidas
        for n, g in enumerate(dups, 1):
            if progress and n % 10 == 0:
                progress(f"Apartando repetidas {n}/{len(dups)}…")
            if not os.path.exists(g["keep"]):
                continue
            for p in g["remove"]:
                if os.path.exists(p) and p != g["keep"]:
                    retire(Path(p), g["keep"])

        # 1. carpetas repetidas
        for m in merges:
            target = Path(m["target"])
            target.mkdir(parents=True, exist_ok=True)
            for s in m["sources"]:
                src_dir = Path(s["folder"])
                if not src_dir.is_dir():
                    continue
                if progress:
                    progress(f"Juntando «{src_dir.name}» en «{target.name}»…")
                for e in list(os.scandir(src_dir)):
                    p = Path(e.path)
                    if not e.is_file():
                        continue
                    if e.name in JUNK or e.name in OUR_FILES:
                        p.unlink()
                        continue
                    dst = target / e.name
                    if dst.exists():
                        if same_file(p, dst):
                            continue  # es el mismo archivo (otro camino): nada que juntar
                        if p.suffix.lower() in AUDIO_EXT and identical(p, dst):
                            retire(p, str(dst))  # copia exacta: se aparta
                            continue
                        dst = free_name(dst)  # mismo nombre pero OTRO archivo: se conservan los dos
                    move(p, dst)
                    path_change[str(p)] = str(dst)
                    log_lines.append(f"MOVIDA    {p}\n          ahora en: {dst}")
                try:
                    src_dir.rmdir()
                    log_lines.append(f"CARPETA   {src_dir} se juntó con {target}")
                except OSError:
                    pass

        # si un archivo que se conserva cambió de carpeta, seguirle la pista
        for k, v in list(dup_of.items()):
            dup_of[k] = path_change.get(v, v)

        rb_stats = None
        if need_rb:
            if progress:
                progress("Corrigiendo rutas en Rekordbox…")
            rb_stats = _rb_apply(path_change, dup_of, retired)
    except Exception as e:
        log(f"Unificar falló, deshaciendo: {e!r}")
        for src, dst in reversed(moves):
            try:
                Path(src).parent.mkdir(parents=True, exist_ok=True)
                safe_move(dst, src)
            except Exception as e2:
                log(f"No pude deshacer {dst} -> {src}: {e2}")
        # quitar carpetas vacías que se alcanzaron a crear en _duplicados
        if dupdir.is_dir():
            for d in sorted((p for p in dupdir.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                try:
                    d.rmdir()
                except OSError:
                    pass
            try:
                dupdir.rmdir()
            except OSError:
                pass
        if isinstance(e, UnifyError):
            raise
        raise UnifyError(f"No se pudo unificar; se deshicieron los cambios. Detalle: {e}")

    # 3. carpetas vacías
    removed = 0
    if remove_empty:
        for d in pl["empty"]:
            dp = Path(d)
            try:
                if not dp.is_dir():
                    continue
                names = [e.name for e in os.scandir(dp)]
                if not all(n in JUNK or n in OUR_FILES for n in names):
                    continue
                for n in names:
                    (dp / n).unlink()
                dp.rmdir()
                removed += 1
                log_lines.append(f"VACÍA     {dp} eliminada")
            except OSError as e:
                log(f"No pude borrar carpeta vacía {dp}: {e}")

    if log_lines:
        dupdir.mkdir(parents=True, exist_ok=True)
        rep = dupdir / f"_registro {datetime.now():%Y-%m-%d %H-%M}.txt"
        rep.write_text("BrainOrder — Unificar repetidos\n\n" + "\n".join(log_lines) + "\n", "utf-8")

    res = {"retired": len(retired), "moved": len(path_change), "empty_removed": removed,
           "backup": backup, "rekordbox": rb_stats, "dup_dir": str(dupdir),
           # para corregir rutas en otros programas de DJ (Traktor…)
           "moved_map": {**path_change, **retired}, "repoint": {k: v for k, v in dup_of.items() if k in retired}}
    log(f"Unificar: {res}")
    return res


def _rb_apply(path_change, dup_of, retired=None):
    """Corrige la colección de Rekordbox después de mover archivos.
    path_change {ruta vieja: ruta nueva}: la pista apunta a la ruta nueva.
    dup_of {repetida apartada: la que se conserva}: la repetida se UNE a la que se conserva (toma su lugar
      en cada playlist, le pasa sus cues si no tenía) y sale de la colección. Antes quedaba apuntando a
      _duplicados y se perdía en cuanto vaciabas esa carpeta.
    También se corrigen las pistas que apuntan a un ACCESO DIRECTO (alias / symlink) hacia un archivo
    movido: antes el acceso directo quedaba roto y la canción perdida.
    Todo en una sola transacción: si algo falla no se guarda nada."""
    try:
        from pyrekordbox import MasterDatabase as DB
    except ImportError:
        from pyrekordbox import Rekordbox6Database as DB
    import rb_coleccion as RC
    import rekordbox_sync
    db = DB(path=rekordbox_sync.RB_DIR / "master.db")
    stats = {"paths": 0, "repointed": 0, "merged": 0, "links": 0}
    undo, anlz = [], []
    try:
        def content(path):
            return rekordbox_sync.content_by_path(db, path)

        link_idx = None

        def links_to(path):
            """Pistas cuya ruta es un acceso directo que apunta (apuntaba) a `path`."""
            nonlocal link_idx
            if link_idx is None:
                link_idx = defaultdict(list)
                for c in db.get_content():
                    p = RC.content_path(c)
                    if p and os.path.islink(p):
                        link_idx[os.path.normcase(os.path.realpath(p))].append(c)
            return list(link_idx.get(os.path.normcase(os.path.realpath(path)), []))

        def put(c, new):
            """c pasa a apuntar a `new`; si ya hay otra pista ahí, se unen (no quedan dos)."""
            other = content(new)
            if other is not None and str(other.ID) != str(c.ID):
                RC.merge(db, c, other, undo)
                stats["merged"] += 1
                return other
            RC.set_path(db, c, new, undo, anlz)
            stats["paths"] += 1
            return c

        for old, new in path_change.items():
            c = content(old)
            if c is not None:
                put(c, new)
            for lc in links_to(old):
                if c is None or str(lc.ID) != str(c.ID):
                    put(lc, new)
                    stats["links"] += 1

        for old, keep in dup_of.items():
            dcs = [x for x in [content(old)] + links_to(old) if x is not None]
            kc = content(keep)
            if kc is None:
                kl = links_to(keep)
                kc = kl[0] if kl else None
            seen = set()
            for dc in dcs:
                if str(dc.ID) in seen:
                    continue
                seen.add(str(dc.ID))
                if kc is not None and str(dc.ID) == str(kc.ID):
                    continue
                stats["repointed"] += db.get_playlist_songs(ContentID=dc.ID).count()
                if kc is None:
                    # la que se conserva no estaba en Rekordbox: esta entrada pasa a apuntarle
                    kc = put(dc, os.path.realpath(keep) if os.path.islink(keep) else keep)
                else:
                    RC.merge(db, dc, kc, undo)
                    stats["merged"] += 1
        db.commit()
        RC.write_anlz(anlz)
        return stats
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
