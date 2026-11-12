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

# 10) la misma canción dos veces en la playlist (dos versiones de Spotify con el MISMO archivo): quitar la de
# más no saca el archivo de la carpeta (la otra fila lo sigue usando)
o = setup()
LA2 = o._analysis()[0]
LA2["tracks"].append({"pos": 5, "id": SP('e'), "name": "Uno", "source": s1})
o._analysis = lambda: [LA2] + [p for p in setup()._analysis() if p["id"] != "pa"]
o._pl_ctx = lambda pid, an=None: ({p["id"]: p for p in o._analysis()}[pid], 'spotify', None, None)
r = o.playlist_tracks_move('pa', [5], None)
assert not o.got.get('ops') and r['result'].get('shared') == 1, (o.got, r['result'])
assert [j['uris'] for j in o.jobs] == [['spotify:track:' + SP('e')]]

# 11) la MISMA canción de Spotify (mismo id) dos veces: no se usa «remove» (quitaría las dos): se reescribe la lista
o = setup()
LA3 = o._analysis()[0]
LA3["tracks"] = [{"pos": 0, "id": SP('a'), "name": "Uno", "source": s1}, {"pos": 1, "id": SP('b'), "name": "Dos", "source": s2},
                 {"pos": 2, "id": SP('a'), "name": "Uno", "source": s1}]
o._analysis = lambda: [LA3]
o._pl_ctx = lambda pid, an=None: (LA3, 'spotify', None, None)
CACHE = {"playlists": [{"id": "pa", "tracks": [{"id": SP('a')}, {"id": SP('b')}, {"id": SP('a')}], "snapshot": "x", "analyzed_snapshot": "x"}]}
o._load_sp = lambda: CACHE
o._update_sp = lambda f: f(CACHE)
class SPr:
    sent = None
    def replace_items(self, pid, uris):
        SPr.sent = uris; return "y"
o._spotify_ready = lambda: SPr()
r = o.playlist_tracks_move('pa', [2], None)
assert SPr.sent == ['spotify:track:' + SP('a'), 'spotify:track:' + SP('b')], SPr.sent
assert not o.jobs and not o.got.get('ops') and [t["id"] for t in CACHE["playlists"][0]["tracks"]] == [SP('a'), SP('b')]
print('mismo id dos veces: lista reescrita', SPr.sent)

# 12) nació en Rekordbox: mover de una playlist de Rekordbox a una de Spotify cambia también la original allá
o = setup()
o._rb_ref = lambda pid, pl=None, entry=None: {'pa': ('rekordbox', 'R1'), 'pb': ('traktor', 'T2')}.get(pid)
o._rb_ready = lambda *refs: None
W = []
o._rb_write = lambda ops: (W.extend(ops), {"added": 1})[1]
r = o.playlist_tracks_move('pa', [1], 'pb')
assert [w['ref'] for w in W] == [('traktor', 'T2'), ('rekordbox', 'R1')], W
assert [x['source'] for x in W[0]['add']] == [str(fb/'uno.mp3')], W[0]
assert s1 in W[1]['remove'] and str(fb/'uno.mp3') in W[1]['remove'], W[1]
print('Rekordbox:', W)

# 13) rekordbox_sync.edit_by_ref con una librería falsa: agrega sin repetir, quita, renombra
import types, rekordbox_sync as RS
class C:
    def __init__(s, p): s.FolderPath = p
class Song:
    def __init__(s, c, n): s.Content, s.ContentID, s.TrackNo = c, id(c), n
class PLx:
    def __init__(s): s.Name, s.Songs = 'MPB (pop)', [Song(C('/m/a.mp3'), 1), Song(C('/m/b.mp3'), 2)]
class DB:
    pl = PLx()
    def __init__(s, path=None): pass
    def get_playlist(s, ID=None): return DB.pl if ID == 'R1' else None
    def remove_from_playlist(s, pl, song): pl.Songs.remove(song)
    def add_to_playlist(s, pl, c): pl.Songs.append(Song(c, len(pl.Songs) + 1))
    def rename_playlist(s, pl, n): pl.Name = n
    def get_content(s, FolderPath=None):
        return types.SimpleNamespace(first=lambda: C(FolderPath))
    def commit(s): pass
    def close(s): pass
sys.modules['pyrekordbox'] = types.SimpleNamespace(MasterDatabase=DB)
RS.rekordbox_running = lambda: False
RS.backup = lambda: Path('/tmp/bk.db')
out = RS.edit_by_ref({}, [{"ref": "R1", "remove": ["/m/a.mp3"], "add": [{"source": "/m/b.mp3"}, {"source": "/m/c.mp3"}],
                           "rename": "MPB"}, {"ref": "R9", "remove": ["/x"]}])
assert [x.Content.FolderPath for x in DB.pl.Songs] == ['/m/b.mp3', '/m/c.mp3'] and DB.pl.Name == 'MPB', DB.pl.Songs
assert out['added'] == 1 and out['removed'] == 1 and out['renamed'] == 1 and out['missing'] == 1, out
print('edit_by_ref:', {k: out[k] for k in ('added', 'removed', 'renamed', 'missing')})
shutil.rmtree(root)
print("OK")
