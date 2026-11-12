"""Corregir en Rekordbox el BPM al doble (÷2) o a la mitad (×2) usando un XML que Rekordbox importa él mismo.

Por qué con XML y no escribiendo directo: la grilla de Rekordbox vive en dos archivos de análisis (ANLZ .DAT y
.EXT) y uno de los formatos (PQT2) no está documentado. Si lo escribiéramos a mano podríamos dañar grillas o cues.
Con «Importar a la colección» es Rekordbox quien reescribe su análisis.

Flujo:
  1. Rekordbox: Archivo → Exportar colección en formato xml (así el XML trae TUS cues, colores, tags, key… exactos).
  2. build(export, {ruta: factor}, salida): copia SOLO esas canciones, con el BPM y la grilla (TEMPO) corregidos,
     y una playlist «BrainOrder · BPM corregido» con ellas. Todo lo demás de cada canción queda igual.
  3. Rekordbox: en «rekordbox xml» abrir la playlist, marcar todas e «Importar a la colección».

Al dividir (BPM al doble) se queda un tiempo sí y uno no, empezando por el «1» del compás (el kick), y el compás
nuevo arranca ahí. Al multiplicar (BPM a la mitad) se agrega un tiempo entre cada uno.
"""
import copy
import os
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote

PLAYLIST = "BrainOrder · BPM corregido"
OUT_NAME = "BrainOrder · BPM corregido.xml"


def path_key(p):
    """Ruta comparable (sin importar mayúsculas, forma de las tildes ni / vs \\)."""
    p = unicodedata.normalize("NFC", str(p or "")).replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    return p.rstrip("/").casefold()


def location_path(loc):
    """file://localhost/Users/x/a%20b.mp3 -> /Users/x/a b.mp3 (Windows: C:/…)."""
    s = str(loc or "")
    for pre in ("file://localhost", "file://"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    s = unquote(s)
    if len(s) > 2 and s[0] == "/" and s[2] == ":":  # /C:/… -> C:/…
        s = s[1:]
    return s


def _f(x, default=0.0):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _num(x, nd):
    s = f"{x:.{nd}f}"
    return s


def _beats(tempos, length_s):
    """TEMPO [(inicio, bpm, battito)] -> [(tiempo, número 1-4, índice del tramo)] de toda la canción."""
    out = []
    for i, (t0, bpm, b) in enumerate(tempos):
        if bpm <= 0:
            continue
        end = tempos[i + 1][0] if i + 1 < len(tempos) else max(length_s, t0) + 1.0
        per = 60.0 / bpm
        k, n = 0, b
        while True:
            t = t0 + k * per
            if t >= end - 1e-6:
                break
            out.append((t, n, i))
            k += 1
            n = n % 4 + 1
            if k > 100000:
                break
    return out


def retempo(tempos, factor, length_s):
    """tempos [(inicio_s, bpm, battito 1-4)] (compás 4/4) -> los TEMPO corregidos con ese factor (0.5 ó 2)."""
    if not tempos:
        return []
    if factor == 2:
        # BPM a la mitad: cada tiempo lento 1/2/3/4 es el 1/3/1/3 del compás rápido
        return [(t0, bpm * 2, 1 if b in (1, 3) else 3) for t0, bpm, b in tempos]
    if factor != 0.5:
        raise ValueError(f"factor {factor}")
    beats = _beats(tempos, length_s)
    if not beats:
        return []
    first_one = next((j for j, (_, n, _) in enumerate(beats) if n == 1), 0)
    start = first_one % 2  # misma paridad que el primer «1» (lo más temprano posible)
    kept = beats[start::2]
    pos_one = (first_one - start) // 2  # índice en kept del primer «1»
    out, seen = [], set()
    for j, (t, _, seg) in enumerate(kept):
        if seg in seen:
            continue
        seen.add(seg)
        num = (j - pos_one) % 4 + 1
        out.append((t, tempos[seg][1] / 2, num))
    return out


def read_tempos(track):
    """-> ([(inicio, bpm, battito)], todos en 4/4)"""
    out, four = [], True
    for te in track.findall("TEMPO"):
        if (te.get("Metro") or "4/4").strip() != "4/4":
            four = False
        out.append((_f(te.get("Inizio")), _f(te.get("Bpm")), int(_f(te.get("Battito"), 1)) or 1))
    out.sort(key=lambda x: x[0])
    return out, four


def fix_track(track, factor):
    """Corrige el TRACK (in place). -> (ok, motivo si no)"""
    tempos, four = read_tempos(track)
    if not tempos:
        return False, "sin grilla en el XML"
    if not four:
        return False, "compás distinto de 4/4"
    new = retempo(tempos, factor, _f(track.get("TotalTime")))
    if not new:
        return False, "no pude calcular la grilla"
    for te in track.findall("TEMPO"):
        track.remove(te)
    pos = len(track)
    for k, el in enumerate(list(track)):  # los TEMPO van antes de las marcas, como los exporta Rekordbox
        if el.tag == "POSITION_MARK":
            pos = k
            break
    for k, (t0, bpm, b) in enumerate(new):
        te = ET.Element("TEMPO", {"Inizio": _num(t0, 3), "Bpm": _num(bpm, 2), "Metro": "4/4", "Battito": str(b)})
        track.insert(pos + k, te)
    avg = _f(track.get("AverageBpm"))
    track.set("AverageBpm", _num((avg * factor) if avg else new[0][1], 2))
    return True, ""


def build(export_path, wanted, out_path, playlist=PLAYLIST, progress=None):
    """wanted {ruta: factor}. Escribe el XML con SOLO esas canciones corregidas + una playlist con ellas.
    -> {done, out, missing:[rutas que no están en el XML], skipped:[(ruta, motivo)], tracks:[{path, before, after}]}"""
    want = {path_key(p): (p, f) for p, f in (wanted or {}).items() if f in (0.5, 2)}
    src = ET.parse(export_path).getroot()
    if src.tag != "DJ_PLAYLISTS":
        raise ValueError("Ese archivo no es un XML exportado por Rekordbox (falta DJ_PLAYLISTS).")
    coll = src.find("COLLECTION")
    if coll is None:
        raise ValueError("El XML no trae la colección (COLLECTION).")
    root = ET.Element("DJ_PLAYLISTS", {"Version": src.get("Version") or "1.0.0"})
    prod = src.find("PRODUCT")
    if prod is not None:
        root.append(copy.deepcopy(prod))
    newc = ET.SubElement(root, "COLLECTION")
    found, ids, skipped, tracks = set(), [], [], []
    all_tr = coll.findall("TRACK")
    for k, tr in enumerate(all_tr):
        if progress and k % 1000 == 0:
            progress(k, len(all_tr))
        key = path_key(location_path(tr.get("Location")))
        if key not in want or key in found:
            continue
        path, factor = want[key]
        t2 = copy.deepcopy(tr)
        before = _f(tr.get("AverageBpm"))
        ok, why = fix_track(t2, factor)
        found.add(key)
        if not ok:
            skipped.append((path, why))
            continue
        newc.append(t2)
        ids.append(t2.get("TrackID"))
        tracks.append({"path": path, "before": before, "after": _f(t2.get("AverageBpm"))})
    newc.set("Entries", str(len(ids)))
    pls = ET.SubElement(root, "PLAYLISTS")
    r = ET.SubElement(pls, "NODE", {"Type": "0", "Name": "ROOT", "Count": "1"})
    p = ET.SubElement(r, "NODE", {"Name": playlist, "Type": "1", "KeyType": "0", "Entries": str(len(ids))})
    for i in ids:
        ET.SubElement(p, "TRACK", {"Key": str(i)})
    try:
        ET.indent(root, space="  ")
    except AttributeError:  # Python < 3.9
        pass
    tmp = str(out_path) + ".tmp"
    ET.ElementTree(root).write(tmp, encoding="UTF-8", xml_declaration=True)
    os.replace(tmp, out_path)
    missing = [p for k, (p, _) in want.items() if k not in found]
    return {"done": len(ids), "out": str(out_path), "missing": missing, "skipped": skipped, "tracks": tracks,
            "playlist": playlist}


def to_location(path):
    """Ruta -> Location como la escribe Rekordbox (espacios y tildes codificados; paréntesis y similares no)."""
    p = str(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://localhost" + quote(p, safe="/:()!$'*,;=@~&+[]")


# ---------------------------------------------------------------- un botón: XML armado desde la colección
KIND = {1: "MP3 File", 4: "M4A File", 5: "FLAC File", 11: "WAV File", 12: "AIFF File"}
# colores de pista de Rekordbox (djmdColor.ID) -> Colour del XML
COLOUR = {1: "0xFF007F", 2: "0xFF0000", 3: "0xFFA500", 4: "0xFFFF00", 5: "0x00FF00", 6: "0x25FDE9",
          7: "0x0000FF", 8: "0x660099"}
HOT_KIND = [1, 2, 3, 5, 6, 7, 8, 9]  # djmdCue.Kind de los hot cues A..H (0 = memory cue)


def grid_tempos(grid):
    """Grilla PQTZ [(tiempo 1-4, bpm, ms)] -> TEMPO [(inicio_s, bpm, battito)] (uno por cada cambio de BPM)."""
    out, last = [], None
    for beat, bpm, ms in grid:
        if last is None or abs(bpm - last) > 0.005:
            out.append((ms / 1000.0, bpm, int(beat) or 1))
            last = bpm
    return out


def db_tracks(con, share_dir, ids):
    """Lee de master.db (solo lectura) lo necesario para el XML de esas canciones."""
    from grillas import read_grid
    ids = [str(i) for i in ids]
    if not ids:
        return []

    def names(table):
        try:
            return {str(i): n for i, n in con.execute(f"SELECT ID, Name FROM {table}")}
        except Exception:
            return {}
    art, alb, gen, lab = names("djmdArtist"), names("djmdAlbum"), names("djmdGenre"), names("djmdLabel")
    keys = {str(i): n for i, n in con.execute("SELECT ID, ScaleName FROM djmdKey")}
    out = []
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        q = ",".join("?" * len(part))
        rows = con.execute(f"""SELECT ID, FolderPath, Title, ArtistID, AlbumID, GenreID, BPM, Length, TrackNo, BitRate,
            Commnt, FileType, Rating, ReleaseYear, RemixerID, LabelID, KeyID, StockDate, ColorID, DJPlayCount,
            AnalysisDataPath, FileSize, DiscNo, ComposerID, Subtitle, SampleRate
            FROM djmdContent WHERE ID IN ({q})""", part).fetchall()
        cues = {}
        for cid, kind, a, b, comment in con.execute(
                f"""SELECT ContentID, Kind, InMsec, OutMsec, Comment FROM djmdCue
                WHERE ContentID IN ({q}) AND COALESCE(rb_local_deleted, 0) = 0""", part):
            cues.setdefault(str(cid), []).append((int(kind or 0), a, b, comment or ""))
        for r in rows:
            (cid, path, title, ar, al, ge, bpm, length, tno, br, com, ft, rating, year, rem, la, key, stock, col,
             plays, anlz, size, disc, comp, sub, sr) = r
            cid = str(cid)
            out.append({"id": cid, "path": path or "", "title": title or "", "artist": art.get(str(ar), ""),
                        "album": alb.get(str(al), ""), "genre": gen.get(str(ge), ""), "bpm": (bpm or 0) / 100.0,
                        "len": int(length or 0), "track_no": int(tno or 0), "bitrate": int(br or 0),
                        "comment": com or "", "kind": KIND.get(int(ft or 0), ""), "rating": int(rating or 0),
                        "year": int(year or 0), "remixer": art.get(str(rem), ""), "label": lab.get(str(la), ""),
                        "key": keys.get(str(key), ""), "added": (stock or "")[:10], "color": int(col or 0),
                        "plays": int(plays or 0), "size": int(size or 0), "disc": int(disc or 0),
                        "composer": art.get(str(comp), ""), "mix": sub or "", "sr": int(sr or 0),
                        "grid": read_grid(share_dir, anlz), "cues": sorted(cues.get(cid, []), key=lambda c: c[1] or 0)})
    return out


def track_element(t, factor):
    """Canción de la colección -> <TRACK> con el BPM y la grilla corregidos (o None, motivo)."""
    tempos = grid_tempos(t["grid"])
    if not tempos:
        return None, "sin grilla"
    new = retempo(tempos, factor, t["len"] or (t["grid"][-1][2] / 1000.0 + 1))
    if not new:
        return None, "no pude calcular la grilla"
    a = {"TrackID": t["id"], "Name": t["title"], "Artist": t["artist"], "Composer": t["composer"],
         "Album": t["album"], "Grouping": "", "Genre": t["genre"], "Kind": t["kind"], "Size": str(t["size"]),
         "TotalTime": str(t["len"]), "DiscNumber": str(t["disc"]), "TrackNumber": str(t["track_no"]),
         "Year": str(t["year"]), "AverageBpm": _num((t["bpm"] or new[0][1] / factor) * factor, 2),
         "DateAdded": t["added"], "BitRate": str(t["bitrate"]), "SampleRate": str(t["sr"]),
         "Comments": t["comment"], "PlayCount": str(t["plays"]), "Rating": str(min(5, max(0, t["rating"])) * 51),
         "Location": to_location(t["path"]), "Remixer": t["remixer"], "Tonality": t["key"], "Label": t["label"],
         "Mix": t["mix"]}
    if t["color"] in COLOUR:
        a["Colour"] = COLOUR[t["color"]]
    el = ET.Element("TRACK", a)
    for t0, bpm, b in new:
        ET.SubElement(el, "TEMPO", {"Inizio": _num(t0, 3), "Bpm": _num(bpm, 2), "Metro": "4/4", "Battito": str(b)})
    for kind, a_ms, b_ms, name in sorted(t["cues"], key=lambda c: c[1] if c[1] is not None else -1):
        if a_ms is None or a_ms < 0:
            continue
        loop = b_ms is not None and b_ms > a_ms
        m = {"Name": name, "Type": "4" if loop else "0", "Start": _num(a_ms / 1000.0, 3),
             "Num": str(HOT_KIND.index(kind)) if kind in HOT_KIND else "-1"}
        if loop:
            m["End"] = _num(b_ms / 1000.0, 3)
        ET.SubElement(el, "POSITION_MARK", m)
    return el, ""


def build_from_db(tracks, factors, out_path, playlist=PLAYLIST):
    """tracks de db_tracks, factors {id: 0.5|2}. Escribe el XML. -> {done, out, skipped, playlist}"""
    root = ET.Element("DJ_PLAYLISTS", {"Version": "1.0.0"})
    ET.SubElement(root, "PRODUCT", {"Name": "rekordbox", "Version": "6.0.0", "Company": "AlphaTheta"})
    coll = ET.SubElement(root, "COLLECTION")
    ids, skipped = [], []
    for t in tracks:
        f = factors.get(t["id"])
        if f not in (0.5, 2):
            continue
        el, why = track_element(t, f)
        if el is None:
            skipped.append((t["path"], why))
            continue
        coll.append(el)
        ids.append(t["id"])
    coll.set("Entries", str(len(ids)))
    pls = ET.SubElement(root, "PLAYLISTS")
    r = ET.SubElement(pls, "NODE", {"Type": "0", "Name": "ROOT", "Count": "1"})
    p = ET.SubElement(r, "NODE", {"Name": playlist, "Type": "1", "KeyType": "0", "Entries": str(len(ids))})
    for i in ids:
        ET.SubElement(p, "TRACK", {"Key": i})
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass
    tmp = str(out_path) + ".tmp"
    ET.ElementTree(root).write(tmp, encoding="UTF-8", xml_declaration=True)
    os.replace(tmp, out_path)
    return {"done": len(ids), "out": str(out_path), "skipped": skipped, "playlist": playlist}


# ---------------------------------------------------------------- dejar Rekordbox apuntando al XML
def settings_files(home=None):
    """rekordbox3.settings posibles (Rekordbox 6/7 y 5), el más nuevo primero."""
    import sys
    from pathlib import Path
    home = Path(home) if home else Path.home()
    if sys.platform == "darwin" or home != Path.home():
        base = home / "Library" / "Application Support" / "Pioneer"
    else:
        base = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming")) / "Pioneer"
    cands = [base / d / "rekordbox3.settings" for d in ("rekordbox7", "rekordbox6", "rekordbox")]
    return [p for p in cands if p.exists()]


def set_xml_pref(xml_path, files):
    """Pone «Biblioteca importada» (rekordbox xml) = xml_path en rekordbox3.settings. Respalda antes.
    Solo cambia ese valor si ya existe. -> lista de archivos cambiados."""
    import re
    import shutil
    from xml.sax.saxutils import escape
    done = []
    val = escape(str(xml_path), {'"': "&quot;"})
    for f in files:
        try:
            s = f.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        pat = re.compile(r'(<VALUE\s+name="bridgeImportedLibraryFile"\s+val=")([^"]*)(")')
        if not pat.search(s):
            continue
        new = pat.sub(lambda m: m.group(1) + val + m.group(3), s, count=1)
        if new != s:
            shutil.copy2(f, f.with_name(f.name + ".brainorder.bak"))
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(new, "utf-8")
            os.replace(tmp, f)
        done.append(str(f))
    return done
