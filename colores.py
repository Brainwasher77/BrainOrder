"""Etiquetas de color de Finder (Mac) para tus carpetas de grupo: verde los grupos, morado «Organizar».
Pedido de Frank (2.51.2): distinguir de un vistazo en BRAIN LIBRARY las carpetas que son grupos.

Finder guarda el color en dos atributos extendidos de la carpeta:
  com.apple.metadata:_kMDItemUserTags  plist con etiquetas «Nombre\\nN» (N = color)
  com.apple.FinderInfo                  32 bytes; el byte 9 lleva el color en los bits 1-3 (N << 1)
Colores: 1 gris, 2 verde, 3 morado, 4 azul, 5 amarillo, 6 rojo, 7 naranja.
Se conservan tus otras etiquetas. En Windows no hay colores de carpeta: no se hace nada.
"""
import plistlib
import subprocess
import sys

from config import log, safe_name

GREEN, PURPLE = 2, 3
NAMES = {GREEN: "Verde", PURPLE: "Morado"}
TAGS = "com.apple.metadata:_kMDItemUserTags"
INFO = "com.apple.FinderInfo"
IS_MAC = sys.platform == "darwin"


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=20)


def _read(path, attr):
    r = _run(["xattr", "-px", attr, str(path)])
    if r.returncode != 0:
        return None
    try:
        return bytes.fromhex("".join(r.stdout.split()))
    except ValueError:
        return None


def _write(path, attr, data):
    return _run(["xattr", "-wx", attr, data.hex(), str(path)]).returncode == 0


def set_color(path, color):
    """Pone la etiqueta de color a la carpeta (si ya la tiene, no toca nada). -> cambió?"""
    if not IS_MAC:
        return False
    changed = False
    raw = _read(path, TAGS)
    try:
        tags = plistlib.loads(raw) if raw else []
    except Exception:
        tags = []
    want = f"{NAMES[color]}\n{color}"
    ours = {f"{n}\n{c}" for c, n in NAMES.items()}
    new = [t for t in tags if t not in ours or t == want]
    if want not in new:
        new.append(want)
    if new != tags:
        changed |= _write(path, TAGS, plistlib.dumps(new, fmt=plistlib.FMT_BINARY))
    info = bytearray(_read(path, INFO) or bytes(32))
    if len(info) < 32:
        info += bytes(32 - len(info))
    b = (info[9] & ~0x0E) | (color << 1)
    if info[9] != b:
        info[9] = b
        changed |= _write(path, INFO, bytes(info))
    return changed


def color_groups(dest_root, trails, default=""):
    """trails {pid: [subcarpetas]}: cada carpeta de grupo (y subgrupo) en verde, la de las sin grupo en
    morado. -> cuántas se pintaron"""
    if not IS_MAC:
        return 0
    from pathlib import Path
    done, n = set(), 0
    for trail in trails.values():
        for k in range(1, len(trail) + 1):
            p = Path(dest_root).joinpath(*[safe_name(x) for x in trail[:k]])
            if str(p) in done or not p.is_dir():
                continue
            done.add(str(p))
            color = PURPLE if default and k == 1 and trail[0].casefold() == default.casefold() else GREEN
            try:
                n += set_color(p, color)
            except Exception as e:
                log(f"color de carpeta {p}: {e!r}")
    return n
