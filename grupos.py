"""Grupos de playlists como CARPETAS (en Rekordbox y en tu disco).

Cada usuario elige una vez (se pregunta al abrir BrainOrder) si sus grupos son:
  - solo para ordenar la lista en BrainOrder (cfg "groups_folders" = False), o
  - carpetas de verdad (True): el grupo «Techno» es la subcarpeta «Techno» dentro de la carpeta de BrainOrder
    en Rekordbox y la carpeta <carpeta de playlists>/Techno/<playlist>/ en el disco.
    Un grupo con «/» es una carpeta dentro de otra: «Crossover / MGNO».

Con grupos-carpetas, grupo y subcarpeta de Rekordbox son LO MISMO:
  - le pones (o cambias, o quitas) el grupo a una playlist en BrainOrder -> se muda en Rekordbox y en el disco
    (cfg "grp_moves" {pid: [subcarpetas]} = lo que falta hacer en Rekordbox; se hace con Rekordbox cerrado);
  - la mueves de subcarpeta en Rekordbox -> su grupo cambia en BrainOrder (Rekordbox manda en lo que hagas allá);
  - al activarlo, si una playlist ya está en una subcarpeta de Rekordbox con otro grupo en BrainOrder, manda
    lo que elegiste (cfg "groups_conflict": "rekordbox" | "group").
Carpeta por defecto (2.51.0, pedido de Frank): con grupos como carpetas, toda playlist SIN grupo va a la carpeta
«Organizar» (cfg "groups_default"), en Rekordbox, en tus otros programas de DJ y en el disco. Quitarle el grupo a
una playlist = mandarla a «Organizar»; sacarla a la carpeta principal en Rekordbox = vuelve a «Organizar».
Aquí solo hay cálculo (sin archivos ni Rekordbox), para poder probarlo.
"""

DEFAULT = "Organizar"

SEP = " / "


def to_trail(group):
    """«Crossover / MGNO» -> ["Crossover", "MGNO"]; "" -> []."""
    return [" ".join(x.split()) for x in str(group or "").split("/") if x.strip()]


def to_group(trail):
    return SEP.join(x for x in trail or [] if x)


def norm(group):
    return to_group(to_trail(group))


def same(a, b):
    return norm(a).casefold() == norm(b).casefold()


def trail_for(pid, groups, default=""):
    """Subcarpetas de una playlist según su grupo (o la carpeta por defecto si no tiene)."""
    return to_trail((groups or {}).get(pid) or default)


def effective_tree(rb_tree, groups, pending, folders_on, mirror_on=True, default="", pids=()):
    """Ruta de subcarpetas de cada playlist en el DISCO: la de Rekordbox (si «Mis carpetas igual que en
    Rekordbox» está activo) y, con grupos-carpetas, la de su grupo (va primero aunque Rekordbox todavía no
    se haya movido, así el disco no tiene que esperar a que cierres Rekordbox)."""
    out = {k: list(v) for k, v in (rb_tree or {}).items()} if mirror_on else {}
    if not folders_on:
        return out
    for pid, g in (groups or {}).items():
        t = to_trail(g)
        if t:
            out[pid] = t
    if default:
        for pid in pids or ():
            if not to_trail((groups or {}).get(pid)):
                out[pid] = to_trail(default)  # sin grupo: a «Organizar»
    for pid, t in (pending or {}).items():
        if t:
            out[pid] = list(t)
        else:
            out.pop(pid, None)  # le quitaste el grupo: vuelve a la carpeta principal
    return out


def activation_plan(groups, rb_tree, present, conflict="rekordbox"):
    """Qué pasa al convertir los grupos en carpetas.
    groups {pid: grupo}; rb_tree {pid: [subcarpetas en Rekordbox]}; present = pids que están en la carpeta de
    BrainOrder en Rekordbox (sueltas o en subcarpetas); conflict = quién manda si no coinciden.
    -> {"groups": {pid: grupo} nuevos, "moves": {pid: [subcarpetas]} por hacer en Rekordbox,
        "from_rb": [pid] que toman el grupo de su subcarpeta, "conflicts": [{pid, group, folder}]}"""
    new = {k: v for k, v in (groups or {}).items() if norm(v)}
    moves, from_rb, conflicts = {}, [], []
    present = set(present or ())
    for pid, trail in (rb_tree or {}).items():
        rg = to_group(trail)
        g = new.get(pid)
        if not g:
            # sin grupo: «no tengo opinión» -> toma la subcarpeta que ya tiene en Rekordbox
            new[pid] = rg
            from_rb.append(pid)
        elif not same(g, rg):
            conflicts.append({"pid": pid, "group": g, "folder": rg})
            if conflict == "group":
                moves[pid] = to_trail(g)
            else:
                new[pid] = rg
    for pid, g in new.items():
        if pid not in (rb_tree or {}) and pid in present and to_trail(g):
            moves[pid] = to_trail(g)  # está suelta en la carpeta de BrainOrder: entra a la de su grupo
    return {"groups": new, "moves": moves, "from_rb": sorted(from_rb), "conflicts": conflicts}


def follow_rekordbox(groups, rb_tree, present, pending, default=""):
    """Lo que moviste de subcarpeta en Rekordbox cambia el grupo en BrainOrder. Las que tienen una mudanza
    pendiente no se tocan (todavía no se hizo) y la mudanza se da por hecha cuando Rekordbox ya coincide.
    -> (grupos, pendientes, cambiadas[pid])"""
    groups = dict(groups or {})
    pending = {k: list(v) for k, v in (pending or {}).items()}
    changed = []
    for pid in list(pending):
        if pid in present and [x.casefold() for x in (rb_tree or {}).get(pid) or []] == \
                [x.casefold() for x in pending[pid]]:
            pending.pop(pid)
    for pid in present or ():
        if pid in pending:
            continue
        rg = to_group((rb_tree or {}).get(pid) or [])
        if default and not rg:
            # suelta en la carpeta principal: con carpeta por defecto, va a «Organizar» (y queda sin grupo)
            if groups.pop(pid, None):
                changed.append(pid)
            pending[pid] = to_trail(default)
            continue
        if default and same(rg, default):
            if groups.pop(pid, None):  # en «Organizar» = sin grupo
                changed.append(pid)
            continue
        if not same(groups.get(pid, ""), rg):
            if rg:
                groups[pid] = rg
            else:
                groups.pop(pid, None)
            changed.append(pid)
    return groups, pending, sorted(changed)
