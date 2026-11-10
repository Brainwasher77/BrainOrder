"""Una sola BrainOrder abierta a la vez (por usuario).

Dos copias abiertas al mismo tiempo guardarían los mismos ajustes y moverían los mismos archivos cada una
por su lado: una pisaría lo que hizo la otra. Al abrir se toma un candado sobre un archivo de la carpeta de
datos; el sistema lo suelta solo cuando el programa se cierra (aunque se cierre de golpe), así que nunca
queda «trabado».
"""
import os
import sys

_HELD = {}


def acquire(path):
    """True si esta es la única copia abierta (y queda marcada). False si ya hay otra."""
    path = str(path)
    if path in _HELD:
        return True
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path, "a+b")
    except OSError:
        return True  # sin poder crear el archivo no se puede saber: no se le impide abrir a nadie
    try:
        if sys.platform.startswith("win"):
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    except Exception:
        _HELD[path] = f  # sistema sin candados de archivo: se deja abrir
        return True
    try:
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()).encode())
        f.flush()
    except OSError:
        pass
    _HELD[path] = f  # se guarda abierto: el candado dura lo que dure el programa
    return True


def release(path):
    f = _HELD.pop(str(path), None)
    if f is not None:
        try:
            f.close()
        except OSError:
            pass
