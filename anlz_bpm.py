"""Corregir directo en Rekordbox el BPM al doble: reescribe la grilla en los archivos de análisis (ANLZ) a la mitad.

Probado por Frank en Rekordbox (12 nov 2026, «Para Amarte Mejor», 180 → 90): la grilla quedó bien y sin errores.

Qué se toca (con Rekordbox cerrado y respaldo antes):
  - ANLZ0000.DAT, etiqueta PQTZ (grilla: por tiempo número 1-4, tempo×100, ms): se queda un tiempo sí y uno no,
    con la paridad del primer «1» del compás; el compás nuevo arranca en ese 1 y el tempo queda a la mitad.
  - ANLZ0000.EXT, etiqueta PQT2 (grilla extendida): los dos tiempos de la cabecera (primero y último) pasan a los
    nuevos, y de sus entradas (2 bytes por tiempo, formato no documentado) se queda la misma mitad que en PQTZ.
  - master.db: djmdContent.BPM a la mitad y contentFile.Hash/Size (md5 y tamaño) de los ANLZ cambiados.
Los demás archivos (.2EX, .3EX: onda y otros datos) no se tocan.
Solo ÷2: para ×2 habría que inventar entradas de PQT2, así que eso sigue por el XML (bpm_xml).
"""
import hashlib
import struct


class AnlzError(Exception):
    pass


def _tags(raw):
    if len(raw) < 12 or raw[:4] != b"PMAI":
        raise AnlzError("no es un archivo de análisis de Rekordbox")
    hl = struct.unpack(">I", raw[4:8])[0]
    i, out = hl, []
    while i + 12 <= len(raw):
        tag = raw[i:i + 4]
        lh, lt = struct.unpack(">II", raw[i + 4:i + 12])
        if lt < 12 or i + lt > len(raw):
            raise AnlzError("archivo de análisis cortado")
        out.append((tag, raw[i:i + lt]))
        i += lt
    return raw[:hl], out


def _join(head, parts):
    head = bytearray(head)
    body = b"".join(p for _, p in parts)
    struct.pack_into(">I", head, 8, len(head) + len(body))
    return bytes(head) + body


def read_beats(dat):
    """bytes del .DAT -> [(número 1-4, tempo×100, ms)]"""
    _, tags = _tags(dat)
    for tag, t in tags:
        if tag == b"PQTZ":
            lh = struct.unpack(">I", t[4:8])[0]
            n = struct.unpack(">I", t[20:24])[0]
            n = min(n, (len(t) - lh) // 8)
            return [struct.unpack(">HHI", t[lh + 8 * k:lh + 8 * k + 8]) for k in range(n)]
    return []


def halve_beats(beats):
    """-> (start, nuevos) : start = 0/1 (desde qué tiempo se toma uno sí y uno no)"""
    if len(beats) < 2:
        raise AnlzError("grilla demasiado corta")
    first = next((k for k, b in enumerate(beats) if b[0] == 1), 0)
    start = first % 2
    kept = beats[start::2]
    pos = (first - start) // 2
    return start, [((j - pos) % 4 + 1, int(round(b[1] / 2)), b[2]) for j, b in enumerate(kept)]


def _pqtz(t, new):
    lh = struct.unpack(">I", t[4:8])[0]
    body = b"".join(struct.pack(">HHI", *b) for b in new)
    h = bytearray(t[:lh])
    struct.pack_into(">I", h, 8, lh + len(body))
    struct.pack_into(">I", h, 20, len(new))
    return bytes(h) + body


def _pqt2(t, start, new):
    lh = struct.unpack(">I", t[4:8])[0]
    if lh < 56:
        raise AnlzError("PQT2 con cabecera desconocida")
    cnt = struct.unpack(">I", t[40:44])[0]
    if lh + 2 * cnt > len(t):
        raise AnlzError("PQT2 cortado")
    ent = [t[lh + 2 * k:lh + 2 * k + 2] for k in range(cnt)]
    kept = ent[start::2][:len(new)]
    h = bytearray(t[:lh])
    struct.pack_into(">HHI", h, 24, *new[0])
    struct.pack_into(">HHI", h, 32, *new[-1])
    struct.pack_into(">I", h, 40, len(kept))
    struct.pack_into(">I", h, 8, lh + 2 * len(kept))
    return bytes(h) + b"".join(kept)


def halve(dat, ext=None):
    """bytes de .DAT (y .EXT si hay) -> (dat nuevo, ext nuevo o None, bpm nuevo, n tiempos). No escribe nada."""
    head, tags = _tags(dat)
    beats = read_beats(dat)
    if not beats:
        raise AnlzError("sin grilla")
    start, new = halve_beats(beats)
    parts = [(tag, _pqtz(t, new) if tag == b"PQTZ" else t) for tag, t in tags]
    d2 = _join(head, parts)
    e2 = None
    if ext:
        h2, t2 = _tags(ext)
        if any(tag == b"PQT2" for tag, _ in t2):
            e2 = _join(h2, [(tag, _pqt2(t, start, new) if tag == b"PQT2" else t) for tag, t in t2])
    # comprobación: lo escrito se vuelve a leer igual
    if read_beats(d2) != new:
        raise AnlzError("la grilla nueva no se lee igual")
    return d2, e2, new[0][1] / 100.0, len(new)


def md5(b):
    return hashlib.md5(b).hexdigest()
