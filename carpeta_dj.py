"""La carpeta donde BrainOrder pone tus playlists dentro de cada programa de DJ («BrainOrder» por defecto).

Si le cambias el nombre (Conexiones), la carpeta se RENOMBRA en cada programa: las playlists siguen siendo
las mismas (no se duplican ni aparecen como «Playlists nuevas»). Si un programa está abierto, el cambio
queda pendiente y se hace solo en cuanto lo cierras (o al Organizar).

cfg["dj_folder_old"]      nombres que tuvo antes (nunca se toman como playlists tuyas nuevas)
cfg["dj_folder_pending"]  {programa: nombre viejo} renombres que faltan por hacer
"""
import config
import destinos

LEGACY = ("Spotify", "SpotiSync", "BrainOrder")  # nombres que usaron versiones anteriores


def current(cfg):
    return (cfg.get("rekordbox_folder") or "BrainOrder").strip() or "BrainOrder"


def names(cfg):
    """Todos los nombres que son (o fueron) la carpeta de BrainOrder."""
    out = [current(cfg)]
    for n in list(cfg.get("dj_folder_old") or []) + list((cfg.get("dj_folder_pending") or {}).values()):
        if n and n not in out:
            out.append(n)
    return out


def for_program(cfg, prog):
    """El nombre que tiene ahora mismo la carpeta en ese programa (el viejo si falta renombrarla)."""
    return (cfg.get("dj_folder_pending") or {}).get(prog) or current(cfg)


def changed(cfg, old):
    """El usuario cambió el nombre: se agenda el renombre en todos los programas activos."""
    new = current(cfg)
    if not old or old == new:
        return
    pend = dict(cfg.get("dj_folder_pending") or {})
    for k in destinos.enabled_keys(cfg):
        if hasattr(destinos.DESTINATIONS[k], "rename_root"):
            pend.setdefault(k, old)  # si ya había uno pendiente, se renombra desde el original
    pend = {k: v for k, v in pend.items() if v != new}
    cfg["dj_folder_pending"] = pend
    cfg["dj_folder_old"] = [n for n in dict.fromkeys(list(cfg.get("dj_folder_old") or []) + [old]) if n != new]
    config.save(cfg)


def detect(cfg, our_names):
    """Para quien cambió el nombre antes de esta versión: si en un programa sigue una carpeta con un nombre
    que usó BrainOrder y adentro están tus playlists de BrainOrder, se agenda renombrarla."""
    new = current(cfg)
    pend = dict(cfg.get("dj_folder_pending") or {})
    found = False
    ours = set(our_names or [])
    if not ours:
        return False
    for k in destinos.enabled_keys(cfg):
        m = destinos.DESTINATIONS[k]
        if k in pend or not hasattr(m, "root_folders"):
            continue
        try:
            folders = m.root_folders(cfg) or {}
        except Exception:
            continue
        now = sum(1 for n in folders.get(new) or [] if n in ours)  # lo que ya está con el nombre actual
        need = max(1, min(5, len(ours) // 2))
        best, score = None, 0
        for name, kids in folders.items():
            if name == new or not kids:
                continue
            hit = sum(1 for n in kids if n in ours)
            if hit >= need and hit >= max(1, len(kids) // 2) and hit > score:
                best, score = name, hit
        if best and score >= now:  # la vieja tiene tus playlists (y su historia): esa pasa a llamarse como la nueva
            pend[k] = best
            found = True
    if found:
        cfg["dj_folder_pending"] = pend
        cfg["dj_folder_old"] = [n for n in dict.fromkeys(list(cfg.get("dj_folder_old") or []) + list(pend.values())) if n != new]
        config.save(cfg)
    return found


def apply(cfg, only=None):
    """Hace los renombres pendientes en los programas cerrados. -> {programa: resultado}, [avisos]"""
    pend = dict(cfg.get("dj_folder_pending") or {})
    done, warn = {}, []
    for k, old in list(pend.items()):
        if only and k not in only:
            continue
        m = destinos.DESTINATIONS.get(k)
        if m is None or not hasattr(m, "rename_root") or not m.available(cfg):
            pend.pop(k)
            continue
        try:
            if m.running():
                warn.append(f"{m.LABEL} está abierto: la carpeta «{old}» se renombra a «{current(cfg)}» en cuanto lo cierres.")
                continue
            r = m.rename_root(cfg, old, current(cfg))
            done[k] = {**(r or {}), "label": m.LABEL}
            pend.pop(k)
        except Exception as e:
            warn.append(f"{m.LABEL}: no pude renombrar la carpeta ({e}).")
            config.log(f"renombrar carpeta en {k}: {e!r}")
    cfg["dj_folder_pending"] = pend
    config.save(cfg)
    return done, warn
