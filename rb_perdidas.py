"""Canciones perdidas en Rekordbox (su archivo ya no está donde Rekordbox lo busca) y entradas que
apuntan a `_duplicados` (se pierden en cuanto vacías esa carpeta).

Para cada una se busca DÓNDE ESTÁ ahora la canción, en este orden:
  1. BrainOrder la movió (Historial): se sigue al archivo exacto.
  2. Otra entrada de la colección que es la misma canción (exacta: mismo tamaño; misma: ISRC o título +
     artista con la misma duración; versión: otra duración).
  3. Un archivo en tu disco que NO está en la colección (mismo tamaño y nombre, o mismo nombre y duración).
Y se repara sin perder nada (rb_coleccion):
  - «reconectar» (el archivo no está en la colección): la pista apunta al archivo. Conserva cues,
    playlists, historial y análisis — lo mismo que «Reubicar» de Rekordbox, pero automático.
  - «unir» (la copia ya está en la colección): la copia toma su lugar en cada playlist (misma posición),
    se queda con sus cues si no tenía, y la perdida sale de la colección.
  - Las que no tienen copia en ninguna parte se pueden sacar de la colección (solo si lo pides).
Todo con respaldo de master.db y Deshacer en Historial.
Solo se tocan canciones cuyo disco está conectado: un disco externo desenchufado no cuenta como perdida.
"""
import os
import re
import unicodedata
from collections import defaultdict

from config import log
from plataforma import native

TOL = 4  # segundos
KINDS = ("exacta", "misma", "version", "sin")
DUP_DIR = "_duplicados"
AUDIO = (".mp3", ".m4a", ".aif", ".aiff", ".wav", ".flac", ".mp4", ".aac", ".alac", ".ogg", ".wma")


def _strip(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def norm_title(s):
    s = _strip(s).replace("’", "'").replace("&", " and ")
    s = re.sub(r"\((original mix|original|explicit|clean|remastered[^)]*|\d{4} remaster[^)]*)\)", "", s)
    s = re.sub(r"\b(feat|ft|featuring)\.?\b.*?(?=[\(\[]|$)", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def norm_stem(name):
    """Nombre de archivo sin extensión, sin tildes ni signos y sin el « (2)» de las copias."""
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"\s*\(\d\)$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", _strip(stem))


def artist_set(s):
    parts = re.split(r",|&| x | y | and |feat\.?|ft\.?|;|/", _strip(s))
    return {re.sub(r"[^a-z0-9]", "", p) for p in parts if re.sub(r"[^a-z0-9]", "", p)}


def _artist_ok(a, b):
    A, B = artist_set(a), artist_set(b)
    return not A or not B or bool(A & B)


def in_dups(path):
    return f"/{DUP_DIR}/" in native(path).replace("\\", "/")


def _volume_ok(path):
    """¿El disco de esta ruta está conectado? (si no, la canción no está perdida: falta el disco)."""
    p = native(path)
    if re.match(r"^[A-Za-z]:[\\/]", p):
        return os.path.isdir(p[:3])
    q = p.replace("//", "/")
    if q.startswith("/Volumes/"):
        parts = q.split("/")
        return len(parts) > 2 and os.path.isdir("/".join(parts[:3]))
    return q.startswith("/")


def _key(p):
    return os.path.normcase(native(p))


def read_tracks(con):
    """con: conexión (sqlcipher o sqlite) a master.db -> lista de pistas de la colección con playlists y cues."""
    rows = con.execute("""SELECT c.ID, c.FolderPath, c.FileNameL, c.Title, a.Name, c.Length, c.FileSize, c.ISRC, c.DJPlayCount
        FROM djmdContent c LEFT JOIN djmdArtist a ON a.ID = c.ArtistID
        WHERE COALESCE(c.rb_local_deleted, 0) = 0""").fetchall()
    cues = defaultdict(int)
    for (cid,) in con.execute("SELECT ContentID FROM djmdCue WHERE COALESCE(rb_local_deleted, 0) = 0"):
        cues[str(cid)] += 1
    names = {str(i): n for i, n in con.execute(
        "SELECT ID, Name FROM djmdPlaylist WHERE COALESCE(rb_local_deleted, 0) = 0 AND COALESCE(Attribute, 0) = 0")}
    pls = defaultdict(list)
    for cid, pid in con.execute("SELECT ContentID, PlaylistID FROM djmdSongPlaylist WHERE COALESCE(rb_local_deleted, 0) = 0"):
        if str(pid) in names:
            pls[str(cid)].append(str(pid))
    out = []
    for cid, path, fname, title, artist, length, size, isrc, plays in rows:
        cid = str(cid)
        if not path:
            continue  # streaming u otras entradas sin archivo
        out.append({"id": cid, "path": path, "fname": fname or path.replace("\\", "/").rsplit("/", 1)[-1],
                    "title": title or "", "artist": artist or "", "len": int(length or 0), "size": int(size or 0),
                    "isrc": (isrc or "").strip().upper(), "plays": int(plays or 0), "cues": cues.get(cid, 0),
                    "pls": sorted(set(pls.get(cid, [])))})
    return out, names


def disk_index(roots, skip_dirs=(DUP_DIR,)):
    """Archivos de audio en esas carpetas (sin _duplicados ni carpetas ocultas) -> lista de dicts."""
    out, seen = [], set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for d, ds, fs in os.walk(root):
            ds[:] = [x for x in ds if not x.startswith(".") and x not in skip_dirs]
            for f in fs:
                if f.startswith(".") or not f.lower().endswith(AUDIO):
                    continue
                p = os.path.join(d, f)
                k = os.path.normcase(p)
                if k in seen:
                    continue
                seen.add(k)
                try:
                    if not os.path.exists(p):
                        continue  # acceso directo roto
                    size = os.path.getsize(p)
                except OSError:
                    continue
                out.append({"path": p, "size": size, "name": f.lower(), "stem": norm_stem(f)})
    return out


def follow_moves(path, moves, limit=20):
    """Sigue los movimientos que hizo BrainOrder (Historial) hasta el lugar actual del archivo."""
    cur, n = _key(path), 0
    while cur in moves and n < limit:
        cur = moves[cur]
        n += 1
    return cur if n else None


def scan(con, exists=None, disk=None, moves=None, duration=None):
    """-> {"items": [...], "total": n, "offline": n}
    exists(path): ¿existe el archivo? · disk: disk_index(...) · moves: {clave origen: clave destino} del
    Historial · duration(path): segundos de un archivo del disco (para comparar con la perdida)."""
    exists = exists or (lambda p: os.path.exists(native(p)))
    moves = moves or {}
    tracks, names = read_tracks(con)
    present, missing, offline = [], [], 0
    for t in tracks:
        if exists(t["path"]):
            present.append(t)
            if in_dups(t["path"]):
                missing.append({**t, "state": "dup"})  # existe, pero en _duplicados: se pierde al vaciarla
        elif _volume_ok(t["path"]):
            missing.append({**t, "state": "lost"})
        else:
            offline += 1
    usable = [t for t in present if not in_dups(t["path"])]
    by_path = {_key(t["path"]): t for t in present}
    by_size, by_isrc, by_title, by_name = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for t in usable:
        if t["size"]:
            by_size[t["size"]].append(t)
        if t["isrc"]:
            by_isrc[t["isrc"]].append(t)
        nt = norm_title(t["title"])
        if nt:
            by_title[nt].append(t)
        by_name[norm_stem(t["fname"])].append(t)
    d_size, d_stem = defaultdict(list), defaultdict(list)
    for f in disk or []:
        if _key(f["path"]) in by_path:
            continue  # ya está en la colección: se usa como entrada, no como archivo suelto
        d_size[f["size"]].append(f)
        d_stem[f["stem"]].append(f)

    def close(a, b):
        return not a["len"] or not b["len"] or abs(a["len"] - b["len"]) <= TOL

    def best(cands, m):
        # la copia con más trabajo encima: cues, playlists, veces tocada; a igualdad, el mismo archivo
        return max(cands, key=lambda t: (t["cues"], len(t["pls"]), t["plays"], t["size"] == m["size"]))

    def entry(t, why):
        return {"id": t["id"], "path": native(t["path"]), "title": t["title"], "artist": t["artist"], "len": t["len"],
                "cues": t["cues"], "pls": [names[p] for p in t["pls"]], "in_collection": True, "why": why}

    def loose(f, why, secs=None):
        return {"id": None, "path": native(f["path"]), "title": os.path.splitext(os.path.basename(f["path"]))[0],
                "artist": "", "len": secs, "cues": 0, "pls": [], "in_collection": False, "why": why}

    items = []
    for m in missing:
        nt, stem = norm_title(m["title"]), norm_stem(m["fname"])
        kind, copy = None, None
        # 1. BrainOrder la movió: es EL MISMO archivo
        dst = follow_moves(m["path"], moves)
        if dst and dst != _key(m["path"]) and exists(dst) and not in_dups(dst):
            t = by_path.get(dst)
            kind, copy = "exacta", (entry(t, "la movió BrainOrder") if t else loose({"path": dst}, "la movió BrainOrder"))
        # 2. otra entrada de la colección
        if not kind and m["size"]:
            c = [t for t in by_size.get(m["size"], []) if t["id"] != m["id"]
                 and ((nt and norm_title(t["title"]) == nt) or norm_stem(t["fname"]) == stem)]
            if c:
                kind, copy = "exacta", entry(best(c, m), "copia exacta en tu colección")
        if not kind and m["isrc"]:
            c = [t for t in by_isrc.get(m["isrc"], []) if t["id"] != m["id"] and close(t, m)]
            if c:
                kind, copy = "misma", entry(best(c, m), "misma canción (ISRC) en tu colección")
        if not kind and nt:
            c = [t for t in by_title.get(nt, []) if t["id"] != m["id"] and _artist_ok(t["artist"], m["artist"]) and close(t, m)]
            if c:
                kind, copy = "misma", entry(best(c, m), "misma canción en tu colección")
        if not kind and stem:
            c = [t for t in by_name.get(stem, []) if t["id"] != m["id"] and close(t, m)]
            if c:
                kind, copy = "misma", entry(best(c, m), "mismo nombre y duración en tu colección")
        # 3. un archivo del disco que no está en la colección
        if not kind and m["size"]:
            c = [f for f in d_size.get(m["size"], []) if f["stem"] == stem or (nt and nt in f["stem"])]
            if c:
                kind, copy = "exacta", loose(c[0], "el mismo archivo en otra carpeta")
        if not kind and stem:
            c = d_stem.get(stem, [])
            for f in c:
                secs = duration(f["path"]) if duration else None
                if secs and m["len"] and abs(secs - m["len"]) <= TOL:
                    kind, copy = "misma", loose(f, "mismo nombre y duración en otra carpeta", secs)
                    break
            if not kind and c and not duration:
                kind, copy = "misma", loose(c[0], "mismo nombre en otra carpeta")
        # versión distinta (no se repara sola: decides tú)
        if not kind and nt:
            c = [t for t in by_title.get(nt, []) if t["id"] != m["id"] and _artist_ok(t["artist"], m["artist"])]
            if c:
                kind, copy = "version", entry(best(c, m), "otra versión (otra duración)")
        kind = kind or "sin"
        action = None
        if copy and kind != "version":
            action = "merge" if copy["in_collection"] else "relink"
        items.append({"id": m["id"], "path": native(m["path"]), "title": m["title"], "artist": m["artist"],
                      "len": m["len"], "size": m["size"], "cues": m["cues"], "pls": [names[p] for p in m["pls"]], "pids": m["pls"],
                      "state": m["state"], "kind": kind, "action": action, "copy": copy})
    items.sort(key=lambda x: (KINDS.index(x["kind"]), _strip(x["artist"]), _strip(x["title"])))
    return {"items": items, "total": len(tracks), "offline": offline}


def apply(db, items, remove_ids=(), progress=None):
    """Repara: «relink» y «merge» de los items elegidos; saca de la colección los de remove_ids (sin copia).
    db abierta para escribir (sin commit). -> (stats, undo, anlz, moved {perdida: ruta nueva})"""
    import rb_coleccion as RC
    from plataforma import rb_path
    stats = {"relinked": 0, "merged": 0, "removed": 0, "skipped": 0}
    undo, anlz, moved = [], [], {}
    claimed = {}  # archivo -> ID de la pista que ya lo tomó en esta pasada (dos perdidas, un archivo: se unen)
    todo = [x for x in items if x.get("action") in ("relink", "merge")]
    for n, x in enumerate(todo, 1):
        if progress and (n % 25 == 0 or n == len(todo)):
            progress(f"Reparando {n}/{len(todo)}…", n / max(1, len(todo)))
        m = db.get_content(ID=x["id"])
        if m is None:
            stats["skipped"] += 1
            continue
        cp = x["copy"]["path"]
        k = db.get_content(ID=x["copy"]["id"]) if x["copy"].get("id") else None
        if k is None:
            import rekordbox_sync
            k = rekordbox_sync.content_by_path(db, cp)
        if k is None and _key(cp) in claimed:
            k = db.get_content(ID=claimed[_key(cp)])
        if k is not None and str(k.ID) != str(m.ID):
            RC.merge(db, m, k, undo)
            stats["merged"] += 1
        elif k is None:
            if not os.path.exists(native(cp)):
                stats["skipped"] += 1
                continue
            RC.set_path(db, m, cp, undo, anlz)
            claimed[_key(cp)] = str(m.ID)
            stats["relinked"] += 1
        else:
            stats["skipped"] += 1
            continue
        moved[native(x["path"])] = native(rb_path(cp))
    for cid in remove_ids or []:
        c = db.get_content(ID=cid)
        if c is not None:
            RC.delete(db, c, undo)
            stats["removed"] += 1
    return stats, undo, anlz, moved


def revert_v1(db, changes, progress=None):
    """Deshace una reparación de la versión 2.19 (solo cambiaba playlists)."""
    done, skipped = 0, 0
    for n, c in enumerate(reversed(changes or []), 1):
        if progress and (n % 25 == 0 or n == len(changes)):
            progress(f"Deshaciendo {n}/{len(changes)}…", n / max(1, len(changes)))
        lost = db.get_content(ID=c["lost"])
        if lost is None:
            skipped += 1  # ya la eliminaste de la colección en Rekordbox
            continue
        if c["op"] == "repointed":
            s = db.get_playlist_songs(ID=c["song"])
            if s is None or str(s.ContentID) != str(c["copy"]):
                skipped += 1
                continue
            s.ContentID = lost.ID
            done += 1
        else:
            pl = db.get_playlist(ID=c["pl"])
            if pl is None or db.get_playlist_songs(PlaylistID=c["pl"], ContentID=lost.ID).first() is not None:
                skipped += 1
                continue
            count = db.get_playlist_songs(PlaylistID=c["pl"]).count()
            track = c["track"] if 1 <= c["track"] <= count + 1 else None
            db.add_to_playlist(pl, lost, track_no=track)
            done += 1
    return done, skipped


def summary(items):
    by = defaultdict(int)
    for x in items:
        by[x["kind"]] += 1
    out = {k: by.get(k, 0) for k in KINDS}
    out["relink"] = sum(1 for x in items if x.get("action") == "relink")
    out["merge"] = sum(1 for x in items if x.get("action") == "merge")
    out["dup"] = sum(1 for x in items if x.get("state") == "dup")
    return out


def log_result(stats, bk):
    log(f"Perdidas en Rekordbox: {stats} (respaldo {bk})")
