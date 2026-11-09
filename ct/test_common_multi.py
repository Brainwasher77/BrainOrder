"""Desmantelar una playlist en varias: cada canción sale una sola vez y su archivo va a la primera elegida
que la tiene (según la prioridad de Reglas)."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import app, config
config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'playlist_common_multi')][0]
root = Path(tempfile.mkdtemp())
fa, fb, fc = root/'A', root/'B', root/'C'
for f in (fa, fb, fc): f.mkdir()
mk = lambda p, d: (p.write_bytes(d), str(p))[1]
s1, s2, s3 = mk(fa/'uno.mp3', b'1'*900), mk(fa/'dos.mp3', b'2'*900), mk(fa/'tres.mp3', b'3'*900)
SP = lambda c: c*22
LA = {"id":"pa","name":"A","folder":str(fa),"tracks":[{"pos":1,"id":SP('a'),"source":s1},{"pos":2,"id":SP('b'),"source":s2},
      {"pos":3,"id":SP('c'),"source":s3},{"pos":4,"id":SP('d'),"source":None}]}
LB = {"id":"pb","name":"B","folder":str(fb),"tracks":[{"pos":1,"id":SP('a'),"source":s1},{"pos":2,"id":SP('b'),"source":s2}]}
LC = {"id":"pc","name":"C","folder":str(fc),"tracks":[{"pos":1,"id":SP('b'),"source":s2},{"pos":2,"id":SP('c'),"source":s3}]}
PL = {"pa": LA, "pb": LB, "pc": LC}
o = A.__new__(A); o._cfg = {"dest_root": str(root), "rules": {"playlist_order": ["pc", "pb"]}}  # C antes que B
o._analysis = lambda: list(PL.values())
o._pl_ctx = lambda pid, an=None: (PL[pid], 'spotify', None, None)
o._is_foreign = lambda pid: False
o._spotify_ready = o._dj_closed = o._set_stage = lambda *a: None
o._task = lambda fn, k, l, files=False: fn()
o._update_sp = lambda f: None
o._build_analysis = lambda light=True: list(PL.values())
jobs = []
o._spotify_do = lambda j: (jobs.append(j), {"state": "ok"})[1]
got = {}
o._relocate_ops = lambda ops, label, extra=None: (got.update(ops=ops), {"moved": len(ops), "changes": {a: str(Path(d)/Path(a).name) for a, d in ops}})[1]
r = o.playlist_common_multi('pa', [{"keep": "pb", "pairs": [[1, 1], [2, 2]]}, {"keep": "pc", "pairs": [[2, 1], [3, 2]]}])
dest = {Path(a).name: Path(d).name for a, d in got['ops']}
print(r['result']['count'], dest, len(jobs[0]['uris']))
assert r['result']['count'] == 3 and len(jobs[0]['uris']) == 3
assert dest == {'uno.mp3': 'B', 'dos.mp3': 'C', 'tres.mp3': 'C'}, dest  # «dos» está en B y C: va a C (primera en Reglas)
shutil.rmtree(root)
print("OK")
