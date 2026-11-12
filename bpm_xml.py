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
    """Ruta -> Location como la escribe Rekordbox (para pruebas)."""
    p = str(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://localhost" + quote(p, safe="/:")
