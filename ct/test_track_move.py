"""Clic derecho en una canción: moverla a otra playlist o quitarla de la playlist (Spotify y carpetas).
Nunca se borra música: el archivo sigue a la playlist, va a otra que la tenga / _Sin Playlist, o a _duplicados
si la de destino ya tiene su propia copia de la misma grabación."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import app, config, plataforma
config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'playlist_tracks_move')][0]
root = Path(tempfile.mkdtemp())
fa, fb, fc = root/'A', root/'B', root/'C'
for f in (fa, fb, fc): f.mkdir()
mk = lambda p, d: (p.write_bytes(d), str(p))[1]
s1, s2, s3 = mk(fa/'uno.mp3', b'1'*900), mk(fa/'dos.mp3', b'2'*900), mk(fa/'tres.mp3', b'3'*900)
b2 = mk(fb/'dos (copia).mp3', b'2'*900)
SP = lambda c: c*22


def setup():
    LA = {"id": "pa", "name": "A", "folder": str(fa), "tracks": [{"pos": 1, "id": SP('a'), "name": "Uno", "source": s1},
          {"pos": 2, "id": SP('b'), "name": "Dos", "source": s2}, {"pos": 3, "id": SP('c'), "name": "Tres", "source": s3},
          {"pos": 4, "id": SP('d'), "name": "Cuatro", "source": None}]}
    LB = {"id": "pb", "name": "B", "folder": str(fb), "tracks": [{"pos": 1, "id": SP('b'), "name": "Dos", "source": b2}]}
    LC = {"id": "pc", "name": "C", "folder": str(fc), "tracks": [{"pos": 1, "id": SP('c'), "name": "Tres", "source": s3}]}
    PL = {"pa": LA, "pb": LB, "pc": LC}
    o = A.__new__(A); o._cfg = {"dest_root": str(root)}
    o._analysis = lambda: list(PL.values())
    o._pl_ctx = lambda pid, an=None: (PL[pid], 'spotify', None, None)
    o._is_foreign = lambda pid: pid == 'pc'
    o._spotify_ready = lambda: None
    o._set_stage = lambda *a: None
    o._task = lambda fn, k, l, files=False: fn()
    o._update_sp = lambda f: None
    o._load_sp = lambda: {"playlists": [], "foreign_ok": []}
    o._build_analysis = lambda light=True: list(PL.values())
    o.jobs, o.got = [], {}
    o._spotify_do = lambda j: (o.jobs.append(j), {"state": "ok"})[1]
    o._relocate_ops = lambda ops, label, extra=None: (o.got.update(ops=ops, extra=extra({a: str(Path(d)/Path(a).name) for a, d in ops}) if extra else None),
                                                       {"moved": len(ops), "changes": {a: str(Path(d)/Path(a).name) for a, d in ops}})[1]
    return o


# 1) mover «Uno» de A a B: entra a B (merge_add), sale de A (remove) y su archivo va a la carpeta de B
o = setup()
r = o.playlist_tracks_move('pa', [1], 'pb')
assert r['result']['added'] == 1, r
kinds = [(j['kind'], j['pid']) for j in o.jobs]
assert kinds == [('merge_add', 'pb'), ('remove', 'pa')], kinds
assert o.jobs[0]['uris'] == ['spotify:track:' + SP('a')] and o.jobs[1]['uris'] == ['spotify:track:' + SP('a')]
assert [(Path(a).name, Path(d).name) for a, d in o.got['ops']] == [('uno.mp3', 'B')], o.got
print('mover:', o.got['ops'])

# 2) mover «Dos» a B, que ya tiene su propia copia de la misma grabación: no se agrega; el de A va a _duplicados
o = setup()
r = o.playlist_tracks_move('pa', [2], 'pb')
assert r['result']['added'] == 0 and r['result']['already'] == 1
assert [j['kind'] for j in o.jobs] == ['remove']
(a, d), = o.got['ops']
assert Path(a).name == 'dos.mp3' and '_duplicados' in d, o.got
assert list(o.got['extra']['dup_of'].values()) == [b2]
print('ya la tenía:', o.got['ops'])

# 3) quitar «Uno» de A: sale de A y, como no está en otra playlist, su archivo va a _Sin Playlist
o = setup()
o._noplaylist_dirs = lambda: []
r = o.playlist_tracks_move('pa', [1], None)
assert [j['kind'] for j in o.jobs] == ['remove']
(a, d), = o.got['ops']
assert Path(d).name == '_Sin Playlist', d
print('quitar:', o.got['ops'])

# 4) quitar «Tres» (también está en C): su archivo va a la carpeta de C
o = setup()
r = o.playlist_tracks_move('pa', [3], None)
(a, d), = o.got['ops']
assert Path(d) == fc, d

# 5) sin archivo: solo cambia la playlist
o = setup()
r = o.playlist_tracks_move('pa', [4], 'pb')
assert not o.got.get('ops') and [j['kind'] for j in o.jobs] == ['merge_add', 'remove']

# 6) no se puede: a una playlist ajena, a sí misma o una posición que ya no existe
o = setup()
for args, txt in ((('pa', [1], 'pc'), 'no se le pueden agregar'), (('pc', [1], None), 'no se le pueden quitar'),
                  (('pa', [1], 'pa'), 'otra playlist'), (('pa', [99], None), 'ya no está')):
    try:
        o.playlist_tracks_move(*args)
        raise AssertionError(args)
    except app.unificar.UnifyError as e:
        assert txt in str(e), (args, e)
assert not o.jobs and not o.got.get('ops')

# 7) a una playlist NUEVA en Spotify: se crea, entra (merge_add) y sale de A; el archivo va a su carpeta
o = setup()
PLS = {}
orig_an = o._analysis
o._analysis = lambda: orig_an() + list(PLS.values())
class SPm:
    def create_playlist(self, name, description=""):
        return {"id": SP('n'), "snapshot_id": "s1", "external_urls": {}}
o._spotify_ready = lambda: SPm()
def upd(f):
    data = {"playlists": []}
    f(data)
    for x in data["playlists"]:
        PLS[x["id"]] = {**x, "folder": str(root/x["name"])}
o._update_sp = upd
ctx0 = o._pl_ctx
o._pl_ctx = lambda pid, an=None: (PLS[pid], 'spotify', None, None) if pid in PLS else ctx0(pid, an)
r = o.playlist_tracks_move('pa', [1], None, {"name": "Bachata Nueva", "spotify": True})
assert r['dst_pid'] == SP('n') and r['result']['created'] and r['result']['into'] == 'Bachata Nueva', r
assert [(j['kind'], j['pid']) for j in o.jobs] == [('merge_add', SP('n')), ('remove', 'pa')], o.jobs
assert [Path(d).name for a, d in o.got['ops']] == ['Bachata Nueva'], o.got
print('nueva en Spotify:', o.got['ops'])

# 8) con un nombre que ya tienes: va a esa (no se crea otra)
o = setup()
r = o.playlist_tracks_move('pa', [1], None, {"name": "  b ", "spotify": True})
assert r['dst_pid'] == 'pb' and not r['result']['created']

# 9) nueva solo en BrainOrder sin archivo: no se puede (y no se crea nada)
o = setup()
try:
    o.playlist_tracks_move('pa', [4], None, {"name": "Otra", "spotify": False}); raise AssertionError
except app.unificar.UnifyError as e:
    assert 'archivo' in str(e)
assert not o.jobs and not (root/'Otra').exists()
shutil.rmtree(root)
print("OK")
