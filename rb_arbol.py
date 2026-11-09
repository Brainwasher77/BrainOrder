"""La carpeta de BrainOrder en Rekordbox como ÁRBOL (con tus subcarpetas), no como una lista plana.

Antes BrainOrder solo miraba lo que estaba directamente dentro de su carpeta. Si organizabas tus playlists
en subcarpetas (Techno / Hard, Latino / Salsa…), las de adentro parecían borradas, el siguiente Organizar
las volvía a crear sueltas (repetidas) y al cambiarle el nombre a la carpeta todas salían como «nuevas».

Aquí todo trabaja con filas (ID, Name, ParentID, Attribute) de djmdPlaylist (vivas), sin importar de dónde
salieron (sqlite directo o pyrekordbox):
    locate(rows, names, known_ids) -> (id de la carpeta, nombre, renombrada?)
    playlists(rows, root_id)       -> {id: {"name", "folder": [subcarpetas desde la carpeta de BrainOrder]}}
    subtree(rows, root_id)         -> ids de todo lo que cuelga de la carpeta (carpetas y playlists)
Attribute: 0 = playlist, 1 = carpeta, 4 = inteligente.
"""

MAX_DEPTH = 50


def _index(rows):
    return {str(r[0]): (str(r[0]), r[1], str(r[2]) if r[2] is not None else None, int(r[3] or 0)) for r in rows}


def top_folder(by_id, pid):
    """Carpeta de la raíz de Rekordbox de la que cuelga pid (None si está suelta en la raíz o no existe)."""
    seen, last = 0, None
    while pid and pid != "root" and pid in by_id and seen < MAX_DEPTH:
        last = by_id[pid]
        pid, seen = last[2], seen + 1
    if last is None or pid != "root" or last[3] != 1:
        return None
    return last


def locate(rows, names, known_ids=()):
    """La carpeta de BrainOrder. names = nombres que tiene o tuvo (el primero manda). Si no está con ninguno,
    se reconoce por sus playlists (los mismos id de la foto) aunque las hayas metido en subcarpetas.
    -> (id, nombre, renombrada) o (None, None, False)."""
    by_id = _index(rows)
    tops = [r for r in by_id.values() if r[2] == "root" and r[3] == 1]
    for n in names or []:
        hit = [r for r in tops if r[1] == n]
        if hit:
            return hit[0][0], hit[0][1], False
    known = [str(k) for k in known_ids or [] if str(k) in by_id]
    if known:
        count = {}
        for k in known:
            t = top_folder(by_id, k)
            if t is not None:
                count[t[0]] = count.get(t[0], 0) + 1
        if count:
            best = max(count, key=count.get)
            if count[best] >= max(1, len(list(known_ids or [])) // 2):
                return best, by_id[best][1], True
    return None, None, False


def subtree(rows, root_id):
    by_parent = {}
    for r in _index(rows).values():
        by_parent.setdefault(r[2], []).append(r)
    out, stack = set(), [str(root_id)]
    while stack:
        cur = stack.pop()
        for r in by_parent.get(cur, []):
            if r[0] not in out:
                out.add(r[0])
                if r[3] == 1:
                    stack.append(r[0])
    return out


def playlists(rows, root_id):
    """Playlists normales dentro de la carpeta (a cualquier profundidad) con su ruta de subcarpetas."""
    if root_id is None:
        return {}
    by_id = _index(rows)
    root_id = str(root_id)
    out = {}
    for rid in subtree(rows, root_id):
        r = by_id[rid]
        if r[3] != 0:
            continue
        trail, cur, seen = [], r[2], 0
        while cur and cur != root_id and cur in by_id and seen < MAX_DEPTH:
            trail.append(by_id[cur][1])
            cur, seen = by_id[cur][2], seen + 1
        out[rid] = {"name": r[1], "folder": list(reversed(trail))}
    return out


def db_rows(db):
    """Filas vivas desde una base abierta con pyrekordbox."""
    out = []
    for p in db.get_playlist():
        if getattr(p, "rb_local_deleted", 0):
            continue
        out.append((p.ID, p.Name, p.ParentID, p.Attribute or 0))
    return out


def sql_rows(con):
    return con.execute("SELECT ID, Name, ParentID, COALESCE(Attribute, 0) FROM djmdPlaylist "
                       "WHERE COALESCE(rb_local_deleted, 0) = 0").fetchall()
