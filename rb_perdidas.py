"""Canciones perdidas en Rekordbox (su archivo ya no está donde Rekordbox lo busca).

Para cada perdida se busca OTRA entrada de la colección que sí existe y es la misma canción:
  exacta  – mismo tamaño de archivo y mismo título o nombre de archivo
  misma   – mismo ISRC, o mismo título + artista con duración ±4 s, o mismo nombre de archivo y duración
  version – mismo título y artista pero otra duración (otra versión: decide el usuario)
  sin     – no hay ninguna copia en la colección
«Reemplazar» cambia cada perdida por su copia DENTRO de sus playlists (misma posición; si la copia ya
estaba en esa playlist, la perdida se quita) y deja la perdida fuera de toda playlist. Borrarla de la
colección lo hace Rekordbox mismo (Archivos perdidos → Eliminar), que limpia todo lo que cuelga de ella.
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


def _strip(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def norm_title(s):
    s = _strip(s).replace("’", "'").replace("&", " and ")
    s = re.sub(r"\((original mix|original|explicit|clean|remastered[^)]*|\d{4} remaster[^)]*)\)", "", s)
    s = re.sub(r"\b(feat|ft|featuring)\.?\b.*?(?=[\(\[]|$)", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def artist_set(s):
    parts = re.split(r",|&| x | y | and |feat\.?|ft\.?|;|/", _strip(s))
    return {re.sub(r"[^a-z0-9]", "", p) for p in parts if re.sub(r"[^a-z0-9]", "", p)}


def _artist_ok(a, b):
    A, B = artist_set(a), artist_set(b)
    return not A or not B or bool(A & B)


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


def scan(con, exists=None):
    """-> {"items": [...], "playlists": {id: nombre}, "total": n, "offline": n}"""
    exists = exists or (lambda p: os.path.exists(native(p)))
    tracks, names = read_tracks(con)
    present, missing, offline = [], [], 0
    for t in tracks:
        if exists(t["path"]):
            present.append(t)
        elif _volume_ok(t["path"]):
            missing.append(t)
        else:
            offline += 1
    by_size, by_isrc, by_title, by_name = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for t in present:
        if t["size"]:
            by_size[t["size"]].append(t)
        if t["isrc"]:
            by_isrc[t["isrc"]].append(t)
        nt = norm_title(t["title"])
        if nt:
            by_title[nt].append(t)
        by_name[t["fname"].lower()].append(t)

    def close(a, b):
        return not a["len"] or not b["len"] or abs(a["len"] - b["len"]) <= TOL

    items = []
    for m in missing:
        nt = norm_title(m["title"])
        kind, cands = None, []
        if m["size"]:
            cands = [t for t in by_size.get(m["size"], [])
                     if (nt and norm_title(t["title"]) == nt) or t["fname"].lower() == m["fname"].lower()]
            kind = "exacta" if cands else None
        if not kind and m["isrc"]:
            cands = [t for t in by_isrc.get(m["isrc"], []) if close(t, m)]
            kind = "misma" if cands else None
        if not kind and nt:
            cands = [t for t in by_title.get(nt, []) if _artist_ok(t["artist"], m["artist"]) and close(t, m)]
            kind = "misma" if cands else None
        if not kind:
            cands = [t for t in by_name.get(m["fname"].lower(), []) if close(t, m)]
            kind = "misma" if cands else None
        if not kind and nt:
            cands = [t for t in by_title.get(nt, []) if _artist_ok(t["artist"], m["artist"])]
            kind = "version" if cands else None
        kind = kind or "sin"
        keep = None
        if cands:
            # la copia con más trabajo encima: cues, playlists, veces tocada; a igualdad, el mismo archivo
            keep = max(cands, key=lambda t: (t["cues"], len(t["pls"]), t["plays"], t["size"] == m["size"]))
        items.append({"id": m["id"], "path": native(m["path"]), "title": m["title"], "artist": m["artist"],
                      "len": m["len"], "cues": m["cues"], "pls": [names[p] for p in m["pls"]], "pids": m["pls"],
                      "kind": kind,
                      "copy": None if not keep else {"id": keep["id"], "path": native(keep["path"]), "title": keep["title"],
                                                     "artist": keep["artist"], "len": keep["len"], "cues": keep["cues"],
                                                     "pls": [names[p] for p in keep["pls"]]}})
    items.sort(key=lambda x: (KINDS.index(x["kind"]), _strip(x["artist"]), _strip(x["title"])))
    return {"items": items, "total": len(tracks), "offline": offline}


def replace(db, pairs, progress=None):
    """db: MasterDatabase abierta para escribir. pairs: [(id perdida, id copia)].
    Devuelve (stats, cambios para deshacer, {ruta perdida: ruta copia})."""
    stats = {"tracks": 0, "repointed": 0, "removed": 0}
    undo, moved = [], {}
    for n, (mid, kid) in enumerate(pairs, 1):
        if progress and (n % 25 == 0 or n == len(pairs)):
            progress(f"Reemplazando en playlists {n}/{len(pairs)}…", n / max(1, len(pairs)))
        m = db.get_content(ID=mid)
        k = db.get_content(ID=kid)
        if m is None or k is None or str(m.ID) == str(k.ID):
            continue
        songs = list(db.get_playlist_songs(ContentID=m.ID))
        if not songs:
            continue
        for s in songs:
            already = db.get_playlist_songs(PlaylistID=s.PlaylistID, ContentID=k.ID).first()
            if already is not None:
                undo.append({"op": "removed", "pl": str(s.PlaylistID), "track": int(s.TrackNo or 0),
                             "lost": str(m.ID), "copy": str(k.ID)})
                db.remove_from_playlist(s.PlaylistID, s)
                stats["removed"] += 1
            else:
                undo.append({"op": "repointed", "song": str(s.ID), "pl": str(s.PlaylistID),
                             "lost": str(m.ID), "copy": str(k.ID)})
                s.ContentID = k.ID
                stats["repointed"] += 1
        stats["tracks"] += 1
        if m.FolderPath and k.FolderPath:
            moved[native(m.FolderPath)] = native(k.FolderPath)
    return stats, undo, moved


def revert(db, changes, progress=None):
    """Deshace replace(): cada canción vuelve a su entrada de antes si nada cambió desde entonces."""
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
    return {k: by.get(k, 0) for k in KINDS}


def log_result(stats, bk):
    log(f"Perdidas en Rekordbox: {stats} (respaldo {bk})")
